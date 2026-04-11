"""Scoring pipeline orchestration."""

import asyncio
import hashlib
import logging
import time
from datetime import UTC, datetime

from pydantic import BaseModel

from job_matcher.config import ScoringConfig, ScoringWeights
from job_matcher.cost_tracker import CostTracker
from job_matcher.models import CvVersion, JdKeywords, Job, MatchScore
from job_matcher.scoring.hard_filters import check_hard_filters
from job_matcher.scoring.keyword_extractor import KeywordExtractor
from job_matcher.scoring.keyword_matcher import compute_keyword_match
from job_matcher.scoring.llm_scorer import LlmScorer
from job_matcher.storage import keywords_store, scores_store

logger = logging.getLogger(__name__)

def _score_key(s):
    return (s.job_id, s.cv_id)


def _kw_key(k):
    return k.job_id


class ScoringRunSummary(BaseModel):
    jobs_processed: int
    pairs_scored: int
    pairs_skipped_fresh: int
    pairs_skipped_filtered: int
    total_cost_usd: float
    duration_seconds: float


def is_score_stale(
    score: MatchScore,
    cv: CvVersion,
    keywords: JdKeywords,
) -> bool:
    if score.cv_content_hash != cv.content_hash:
        return True
    current_kw_hash = _compute_keyword_hash(keywords.must_have)
    return score.jd_keyword_hash != current_kw_hash


def compute_final_score(
    keyword_score: float,
    semantic_score: float,
    weights: "ScoringWeights",
) -> float:
    return round(
        float(weights.keyword) * keyword_score + float(weights.semantic) * semantic_score,
        4,
    )


def _compute_keyword_hash(keywords: list[str]) -> str:
    joined = "|".join(sorted(keywords))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class ScoringPipeline:
    def __init__(
        self,
        config: ScoringConfig,
        anthropic_client,
        cost_tracker: CostTracker,
    ):
        self._config = config
        self._cost_tracker = cost_tracker
        self._extractor = KeywordExtractor(
            anthropic_client, config.llm_model, cost_tracker
        )
        self._scorer = LlmScorer(anthropic_client, config.llm_model, cost_tracker)
        self._semaphore = asyncio.Semaphore(config.concurrent_llm_calls)

    async def score_jobs(
        self,
        jobs: list[Job],
        cvs: list[CvVersion],
        only_new: bool = True,
        max_total_pairs: int | None = None,
        show_progress: bool = False,
    ) -> ScoringRunSummary:
        from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

        start = time.monotonic()
        pairs_scored = 0
        pairs_skipped_fresh = 0
        pairs_skipped_filtered = 0
        jobs_processed = 0
        total_pairs = len(jobs) * len(cvs)

        existing_scores = {
            (s.job_id, s.cv_id): s for s in scores_store.all()
        }
        existing_keywords = {kw.job_id: kw for kw in keywords_store.all()}

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            disable=not show_progress,
        )
        with progress:
            task = progress.add_task("Scoring", total=total_pairs)

            for job in jobs:
                jobs_processed += 1

                # Hard filter check
                filter_result = check_hard_filters(job, self._config.hard_filters)
                if filter_result.triggered:
                    for cv in cvs:
                        if (job.id, cv.id) not in existing_scores:
                            zero_score = self._make_filtered_score(
                                job, cv, filter_result.reason or "unknown_filter"
                            )
                            scores_store.upsert(zero_score, _score_key)
                            pairs_skipped_filtered += 1
                        progress.advance(task)
                    continue

                # Keyword extraction (cached)
                kw_entry = existing_keywords.get(job.id)
                if kw_entry is None or kw_entry.job_description_hash != hashlib.sha256(
                    job.description.encode("utf-8")
                ).hexdigest():
                    kw_entry = await self._extractor.extract(job)
                    keywords_store.upsert(kw_entry, _kw_key)
                    existing_keywords[job.id] = kw_entry

                # Score each CV
                for cv in cvs:
                    if max_total_pairs is not None and pairs_scored >= max_total_pairs:
                        progress.advance(task)
                        break

                    existing = existing_scores.get((job.id, cv.id))
                    if only_new and existing and not is_score_stale(existing, cv, kw_entry):
                        pairs_skipped_fresh += 1
                        progress.advance(task)
                        continue

                    # Keyword match (pure Python)
                    kw_result = compute_keyword_match(kw_entry.must_have, cv.content)

                    # Semantic score (LLM)
                    llm_result = await self._scorer.score_one(
                        job, cv, kw_entry.must_have
                    )

                    final = compute_final_score(
                        kw_result.score, llm_result.semantic_score, self._config.weights
                    )
                    kw_hash = _compute_keyword_hash(kw_entry.must_have)

                    match_score = MatchScore(
                        job_id=job.id,
                        cv_id=cv.id,
                        keyword_score=kw_result.score,
                        keywords_required=kw_result.required,
                        keywords_matched=kw_result.matched,
                        keywords_missing=kw_result.missing,
                        semantic_score=llm_result.semantic_score,
                        reasoning=llm_result.reasoning,
                        green_flags=llm_result.green_flags,
                        red_flags=llm_result.red_flags,
                        llm_model_used=self._config.llm_model,
                        final_score=final,
                        hard_filter_triggered=None,
                        scored_at=datetime.now(UTC),
                        cv_content_hash=cv.content_hash,
                        jd_keyword_hash=kw_hash,
                    )
                    scores_store.upsert(match_score, _score_key)
                    pairs_scored += 1
                    progress.advance(task)

                if max_total_pairs is not None and pairs_scored >= max_total_pairs:
                    break

        duration = time.monotonic() - start
        cost_summary = self._cost_tracker.summary_by_operation()
        total_cost = sum(cost_summary.values())

        return ScoringRunSummary(
            jobs_processed=jobs_processed,
            pairs_scored=pairs_scored,
            pairs_skipped_fresh=pairs_skipped_fresh,
            pairs_skipped_filtered=pairs_skipped_filtered,
            total_cost_usd=round(total_cost, 4),
            duration_seconds=round(duration, 1),
        )

    def _make_filtered_score(
        self, job: Job, cv: CvVersion, reason: str
    ) -> MatchScore:
        return MatchScore(
            job_id=job.id,
            cv_id=cv.id,
            keyword_score=0.0,
            keywords_required=[],
            keywords_matched=[],
            keywords_missing=[],
            semantic_score=0.0,
            reasoning=f"Hard-filtered: {reason}",
            green_flags=[],
            red_flags=[],
            llm_model_used=self._config.llm_model,
            final_score=0.0,
            hard_filter_triggered=reason,
            scored_at=datetime.now(UTC),
            cv_content_hash=cv.content_hash,
            jd_keyword_hash="",
        )
