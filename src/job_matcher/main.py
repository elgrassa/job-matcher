"""High-level workflow orchestration.

Coordinates scraping, dedup, scoring, and tracking in a single run.
Each function is designed to be called from CLI commands.
"""

import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime

from job_matcher.cache import LocalCache
from job_matcher.config import (
    load_anthropic_settings,
    load_apify_settings,
    load_platforms_config,
    load_scoring_config,
)
from job_matcher.cost_tracker import CostTracker
from job_matcher.cv_loader import load_all_registered_cvs
from job_matcher.dedup import canonicalize_raw
from job_matcher.models import ScrapeRun
from job_matcher.scoring.pipeline import ScoringPipeline, ScoringRunSummary
from job_matcher.scrapers.registry import list_enabled_scrapers
from job_matcher.storage import jobs_store, sources_store

logger = logging.getLogger(__name__)


def run_scrape(
    platforms: list[str] | None = None,
    max_results: int | None = None,
    use_cache: bool = True,
    cache_max_age_hours: int = 24,
) -> list[ScrapeRun]:
    """Scrape enabled platforms, dedup, store. Returns audit records."""
    apify = load_apify_settings()
    platforms_config = load_platforms_config()
    scrapers = list_enabled_scrapers(platforms_config, apify.APIFY_TOKEN)
    cache = LocalCache() if use_cache else None

    runs: list[ScrapeRun] = []
    for scraper in scrapers:
        name = scraper.platform_name
        if platforms and name not in platforms:
            continue

        start = time.monotonic()
        cache_hit = False

        # Check cache first
        if cache:
            cached = cache.load(name, max_age_hours=cache_max_age_hours)
            if cached is not None:
                cache_hit = True
                raw_jobs = []
                for item in cached:
                    with contextlib.suppress(Exception):
                        raw_jobs.append(scraper.parse_item(item))
                logger.info("Cache hit for %s: %d items", name, len(raw_jobs))
            else:
                raw_jobs = list(scraper.scrape(max_results=max_results))
                # Cache the raw dicts for next time
                if raw_jobs:
                    cache.store(name, [rj.raw for rj in raw_jobs])
        else:
            raw_jobs = list(scraper.scrape(max_results=max_results))

        raw_count = len(raw_jobs)

        # Dedup and store — track unique IDs
        seen_ids: set[str] = set()
        for raw_job in raw_jobs:
            job, source = canonicalize_raw(raw_job)
            seen_ids.add(job.id)
            jobs_store.upsert(job, lambda j: j.id)
            sources_store.upsert(source, lambda s: (s.job_id, s.platform))

        unique_count = len(seen_ids)
        duration = time.monotonic() - start
        run = ScrapeRun(
            id=f"{name}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}",
            initiated_at=datetime.now(UTC),
            platform=name,
            jobs_fetched=raw_count,
            raw_count=raw_count,
            unique_count=unique_count,
            cache_hit=cache_hit,
            duration_seconds=round(duration, 1),
        )
        runs.append(run)
        logger.info(
            "Scraped %s: %d raw -> %d unique in %.1fs (cache_hit=%s)",
            name, raw_count, unique_count, duration, cache_hit,
        )

    return runs


def run_score(
    only_new: bool = True,
    max_total_pairs: int | None = None,
) -> ScoringRunSummary:
    """Score all jobs against all CVs. Returns scoring summary."""
    scoring_config = load_scoring_config()
    anthropic_settings = load_anthropic_settings()

    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=anthropic_settings.ANTHROPIC_API_KEY)
    tracker = CostTracker()
    pipeline = ScoringPipeline(scoring_config, client, tracker)

    cvs = load_all_registered_cvs(scoring_config)
    jobs = jobs_store.all()

    return asyncio.run(
        pipeline.score_jobs(
            jobs, cvs, only_new=only_new,
            max_total_pairs=max_total_pairs,
            show_progress=True,
        )
    )
