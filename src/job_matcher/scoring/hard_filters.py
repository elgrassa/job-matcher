"""Pre-LLM hard filters for known-incompatible jobs."""

from pydantic import BaseModel

from job_matcher.config import HardFilterConfig
from job_matcher.models import Job


class HardFilterResult(BaseModel):
    triggered: bool
    reason: str | None


def check_hard_filters(job: Job, config: HardFilterConfig) -> HardFilterResult:
    """Check filters in priority order. Return the first that triggers (short-circuit)."""
    checks = (
        lambda: _check_eu_citizenship(job.description, config.eu_citizenship_keywords),
        lambda: _check_onsite_location(job, config.onsite_compatible_cities),
        lambda: _check_hybrid_rejection(job, config.reject_hybrid),
        lambda: _check_us_territory_restricted(
            job, config.us_location_keywords, config.us_work_authorization_keywords
        ),
        lambda: _check_rate_floor(job, config.min_daily_rate_eur, config.min_hourly_rate_eur),
    )
    for check in checks:
        reason = check()
        if reason is not None:
            return HardFilterResult(triggered=True, reason=reason)
    return HardFilterResult(triggered=False, reason=None)


def _check_eu_citizenship(description: str, keywords: list[str]) -> str | None:
    desc_lower = description.lower()
    for kw in keywords:
        if kw.lower() in desc_lower:
            return "eu_citizenship_required"
    return None


def _check_onsite_location(job: Job, compatible_cities: list[str]) -> str | None:
    if job.remote_type != "onsite":
        return None
    if job.location is None:
        return None
    loc_lower = job.location.lower()
    for city in compatible_cities:
        if city.lower() in loc_lower:
            return None
    return f"onsite_in_{job.location.split(',')[0].strip().lower().replace(' ', '_')}"


def _check_hybrid_rejection(job: Job, reject_hybrid: bool) -> str | None:
    if not reject_hybrid:
        return None
    if job.remote_type != "hybrid":
        return None
    return "hybrid_rejected"


def _check_us_territory_restricted(
    job: Job,
    us_location_keywords: list[str],
    us_work_auth_keywords: list[str],
) -> str | None:
    # Check description for US work authorization requirements
    if job.description:
        desc_lower = job.description.lower()
        for kw in us_work_auth_keywords:
            if kw.lower() in desc_lower:
                return "us_work_authorization_required"

    # Check location for US indicators
    if job.location:
        loc_lower = job.location.lower()
        for kw in us_location_keywords:
            if kw.lower() in loc_lower:
                return "us_territory_restricted"
    return None


def _check_rate_floor(
    job: Job, min_day_eur: float, min_hour_eur: float
) -> str | None:
    if job.salary_currency != "EUR":
        return None
    if job.salary_min is None:
        return None
    if job.salary_period == "day" and job.salary_min < min_day_eur:
        return f"rate_below_floor_{int(job.salary_min)}eur_day"
    if job.salary_period == "hour" and job.salary_min < min_hour_eur:
        return f"rate_below_floor_{int(job.salary_min)}eur_hour"
    return None
