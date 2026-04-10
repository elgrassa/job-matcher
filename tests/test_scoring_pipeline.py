"""Tests for scoring pipeline."""

import pytest

from job_matcher.models import CvVersion, JdKeywords, MatchScore
from job_matcher.scoring.pipeline import (
    compute_final_score,
    is_score_stale,
)

TS = "2026-04-10T10:00:00+00:00"


def _cv(cv_id: str = "test_cv", content_hash: str = "sha256:" + "a" * 64) -> CvVersion:
    return CvVersion(
        id=cv_id,
        name="Test",
        file_path="cvs/test.md",
        content_hash=content_hash,
        content="Java Python CI/CD 15 years.",
        char_count=30,
        loaded_at=TS,
    )


def _keywords(job_id: str = "a3f7c2b8e1d94f56") -> JdKeywords:
    return JdKeywords(
        job_id=job_id,
        must_have=["java", "python"],
        nice_to_have=["docker"],
        extracted_at=TS,
        job_description_hash="abc123",
    )


def _score(
    job_id: str = "a3f7c2b8e1d94f56",
    cv_id: str = "test_cv",
    cv_hash: str = "sha256:" + "a" * 64,
    kw_hash: str = "",
) -> MatchScore:
    import hashlib

    if not kw_hash:
        kw_hash = hashlib.sha256(b"java|python").hexdigest()
    return MatchScore(
        job_id=job_id,
        cv_id=cv_id,
        keyword_score=0.5,
        keywords_required=["java", "python"],
        keywords_matched=["java"],
        keywords_missing=["python"],
        semantic_score=0.7,
        reasoning="Test",
        green_flags=["java"],
        red_flags=["python missing"],
        llm_model_used="test",
        final_score=0.63,
        hard_filter_triggered=None,
        scored_at=TS,
        cv_content_hash=cv_hash,
        jd_keyword_hash=kw_hash,
    )


class TestIsScoreStale:
    def test_cv_hash_mismatch(self):
        cv = _cv(content_hash="sha256:" + "b" * 64)
        kw = _keywords()
        score = _score(cv_hash="sha256:" + "a" * 64)
        assert is_score_stale(score, cv, kw) is True

    def test_keyword_hash_mismatch(self):
        cv = _cv()
        kw = _keywords()
        score = _score(kw_hash="stale_hash")
        assert is_score_stale(score, cv, kw) is True

    def test_fresh_when_hashes_match(self):
        import hashlib

        cv = _cv()
        kw = _keywords()
        kw_hash = hashlib.sha256(b"java|python").hexdigest()
        score = _score(cv_hash=cv.content_hash, kw_hash=kw_hash)
        assert is_score_stale(score, cv, kw) is False


class TestComputeFinalScore:
    def test_weighted_blend(self):
        from job_matcher.config import ScoringWeights

        weights = ScoringWeights(keyword=0.35, semantic=0.65)
        result = compute_final_score(0.8, 0.9, weights)
        expected = 0.35 * 0.8 + 0.65 * 0.9
        assert result == round(expected, 4)

    def test_zero_scores(self):
        from job_matcher.config import ScoringWeights

        weights = ScoringWeights(keyword=0.35, semantic=0.65)
        assert compute_final_score(0.0, 0.0, weights) == 0.0

    def test_perfect_scores(self):
        from job_matcher.config import ScoringWeights

        weights = ScoringWeights(keyword=0.35, semantic=0.65)
        assert compute_final_score(1.0, 1.0, weights) == 1.0


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_with_mocks(
        self, mock_anthropic_client, tmp_path, monkeypatch, sample_job_model
    ):
        from job_matcher.config import (
            HardFilterConfig,
            ScoringConfig,
            ScoringWeights,
            WarningConfig,
        )
        from job_matcher.cost_tracker import CostTracker
        from job_matcher.models import CostLedgerEntry, JdKeywords, MatchScore
        from job_matcher.scoring.pipeline import ScoringPipeline
        from job_matcher.storage import JsonStore

        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()

        cost_s = JsonStore(
            file_path=tmp_path / "cost.json", model=CostLedgerEntry, lock_dir=lock_dir
        )
        kw_s = JsonStore(
            file_path=tmp_path / "keywords.json", model=JdKeywords, lock_dir=lock_dir
        )
        score_s = JsonStore(
            file_path=tmp_path / "scores.json", model=MatchScore, lock_dir=lock_dir
        )
        monkeypatch.setattr("job_matcher.cost_tracker.cost_store", cost_s)
        monkeypatch.setattr("job_matcher.scoring.pipeline.keywords_store", kw_s)
        monkeypatch.setattr("job_matcher.scoring.pipeline.scores_store", score_s)
        # cost_store is patched via cost_tracker module, not keyword_extractor

        config = ScoringConfig(
            weights=ScoringWeights(keyword=0.35, semantic=0.65),
            warning=WarningConfig(),
            hard_filters=HardFilterConfig(
                eu_citizenship_keywords=["eu citizenship required"],
                onsite_compatible_cities=["wroclaw"],
            ),
            cvs=[],
            default_cv="test_cv",
        )

        kw_response = '{"must_have": ["java", "python"], "nice_to_have": ["docker"]}'
        score_response = '{"semantic_score": 0.82, "reasoning": "Good", "green_flags": ["java"], "red_flags": []}'
        client = mock_anthropic_client(responses=[kw_response, score_response])
        tracker = CostTracker()

        pipeline = ScoringPipeline(config, client, tracker)
        cv = _cv()
        summary = await pipeline.score_jobs([sample_job_model], [cv], only_new=True)

        assert summary.jobs_processed == 1
        assert summary.pairs_scored == 1
        assert score_s.count() == 1
        stored = score_s.all()[0]
        assert stored.semantic_score == 0.82
        assert stored.keyword_score > 0  # java and python should match

    @pytest.mark.asyncio
    async def test_hard_filtered_jobs_skip_llm(
        self, mock_anthropic_client, tmp_path, monkeypatch
    ):
        from datetime import UTC, datetime

        from job_matcher.config import (
            HardFilterConfig,
            ScoringConfig,
            ScoringWeights,
            WarningConfig,
        )
        from job_matcher.cost_tracker import CostTracker
        from job_matcher.models import (
            CostLedgerEntry,
            JdKeywords,
            Job,
            MatchScore,
        )
        from job_matcher.scoring.pipeline import ScoringPipeline
        from job_matcher.storage import JsonStore

        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()

        cost_s = JsonStore(
            file_path=tmp_path / "cost.json", model=CostLedgerEntry, lock_dir=lock_dir
        )
        kw_s = JsonStore(
            file_path=tmp_path / "keywords.json", model=JdKeywords, lock_dir=lock_dir
        )
        score_s = JsonStore(
            file_path=tmp_path / "scores.json", model=MatchScore, lock_dir=lock_dir
        )
        monkeypatch.setattr("job_matcher.cost_tracker.cost_store", cost_s)
        monkeypatch.setattr("job_matcher.scoring.pipeline.keywords_store", kw_s)
        monkeypatch.setattr("job_matcher.scoring.pipeline.scores_store", score_s)

        config = ScoringConfig(
            weights=ScoringWeights(keyword=0.35, semantic=0.65),
            warning=WarningConfig(),
            hard_filters=HardFilterConfig(
                eu_citizenship_keywords=["eu citizenship required"],
                onsite_compatible_cities=["wroclaw"],
            ),
            cvs=[],
            default_cv="test_cv",
        )

        # This job has EU citizenship requirement — should be hard-filtered
        filtered_job = Job(
            id="b1c2d3e4f5a6b7c8",
            title="Security Analyst",
            company="Gov Corp",
            location="London",
            description="EU citizenship required. NATO clearance.",
            salary_min=500.0,
            salary_max=700.0,
            salary_currency="EUR",
            salary_period="day",
            employment_type="contract",
            remote_type="remote",
            seniority="senior",
            posted_at=None,
            first_seen_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
            scraped_at=datetime.now(UTC),
        )

        client = mock_anthropic_client(responses=[])  # No LLM calls expected
        tracker = CostTracker()
        pipeline = ScoringPipeline(config, client, tracker)
        cv = _cv()

        summary = await pipeline.score_jobs([filtered_job], [cv])
        assert summary.pairs_skipped_filtered == 1
        assert summary.pairs_scored == 0
        assert client.call_count == 0  # No LLM calls made

    @pytest.mark.asyncio
    async def test_max_total_pairs_stops_early(
        self, mock_anthropic_client, tmp_path, monkeypatch, sample_job_model
    ):
        from job_matcher.config import (
            HardFilterConfig,
            ScoringConfig,
            ScoringWeights,
            WarningConfig,
        )
        from job_matcher.cost_tracker import CostTracker
        from job_matcher.models import CostLedgerEntry, JdKeywords, MatchScore
        from job_matcher.scoring.pipeline import ScoringPipeline
        from job_matcher.storage import JsonStore

        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()

        cost_s = JsonStore(
            file_path=tmp_path / "cost.json", model=CostLedgerEntry, lock_dir=lock_dir
        )
        kw_s = JsonStore(
            file_path=tmp_path / "keywords.json", model=JdKeywords, lock_dir=lock_dir
        )
        score_s = JsonStore(
            file_path=tmp_path / "scores.json", model=MatchScore, lock_dir=lock_dir
        )
        monkeypatch.setattr("job_matcher.cost_tracker.cost_store", cost_s)
        monkeypatch.setattr("job_matcher.scoring.pipeline.keywords_store", kw_s)
        monkeypatch.setattr("job_matcher.scoring.pipeline.scores_store", score_s)
        # cost_store is patched via cost_tracker module, not keyword_extractor

        config = ScoringConfig(
            weights=ScoringWeights(keyword=0.35, semantic=0.65),
            warning=WarningConfig(),
            hard_filters=HardFilterConfig(
                eu_citizenship_keywords=[],
                onsite_compatible_cities=["wroclaw"],
            ),
            cvs=[],
            default_cv="test_cv",
        )

        kw = '{"must_have": ["java"], "nice_to_have": []}'
        sc = '{"semantic_score": 0.7, "reasoning": "OK", "green_flags": [], "red_flags": []}'
        # 1 keyword extraction + 1 scoring = 2 LLM calls for max_total_pairs=1
        client = mock_anthropic_client(responses=[kw, sc])
        tracker = CostTracker()
        pipeline = ScoringPipeline(config, client, tracker)

        cv1 = _cv("cv_a")
        cv2 = _cv("cv_b")
        summary = await pipeline.score_jobs(
            [sample_job_model], [cv1, cv2], max_total_pairs=1
        )
        assert summary.pairs_scored == 1  # Stopped at 1, didn't score cv2
