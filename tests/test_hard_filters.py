"""Tests for hard filters."""

import pytest

from job_matcher.config import HardFilterConfig
from job_matcher.models import Job
from job_matcher.scoring.hard_filters import check_hard_filters

TS = "2026-04-10T10:00:00+00:00"


def _config(**overrides) -> HardFilterConfig:
    base = {
        "min_daily_rate_eur": 320,
        "min_hourly_rate_eur": 40,
        "reject_hybrid": True,
        "eu_citizenship_keywords": [
            "eu citizenship required",
            "must be eu citizen",
            "eu nationals only",
        ],
        "us_work_authorization_keywords": [
            "must be authorized to work in the united states",
            "us work authorization required",
            "must reside in the united states",
        ],
        "us_location_keywords": ["united states", ", us", "usa"],
        "onsite_compatible_cities": ["wroclaw", "wrocław", "remote"],
    }
    base.update(overrides)
    return HardFilterConfig(**base)


def _job(**overrides) -> Job:
    base = {
        "id": "a3f7c2b8e1d94f56",
        "title": "SDET",
        "company": "Acme",
        "location": "Remote",
        "description": "A normal job posting.",
        "salary_min": 400.0,
        "salary_max": 500.0,
        "salary_currency": "EUR",
        "salary_period": "day",
        "employment_type": "b2b",
        "remote_type": "remote",
        "seniority": "senior",
        "posted_at": TS,
        "first_seen_at": TS,
        "last_seen_at": TS,
        "scraped_at": TS,
    }
    base.update(overrides)
    return Job(**base)


class TestEuCitizenship:
    @pytest.mark.parametrize(
        "description, expected",
        [
            ("EU citizenship required for this role", "eu_citizenship_required"),
            ("Must be EU citizen to apply", "eu_citizenship_required"),
            ("EU nationals only", "eu_citizenship_required"),
            ("We welcome candidates from anywhere", None),
            ("Open to all EU residents", None),
        ],
    )
    def test(self, description: str, expected: str | None):
        job = _job(description=description)
        result = check_hard_filters(job, _config())
        if expected:
            assert result.triggered is True
            assert result.reason == expected
        else:
            assert result.triggered is False


class TestOnsiteLocation:
    def test_remote_jobs_never_trigger(self):
        job = _job(remote_type="remote", location="Berlin, Germany")
        result = check_hard_filters(job, _config())
        assert result.triggered is False

    def test_onsite_wroclaw_does_not_trigger(self):
        job = _job(remote_type="onsite", location="Wroclaw, Poland")
        result = check_hard_filters(job, _config())
        assert result.triggered is False

    def test_onsite_berlin_triggers(self):
        job = _job(remote_type="onsite", location="Berlin, Germany")
        result = check_hard_filters(job, _config())
        assert result.triggered is True
        assert result.reason == "onsite_in_berlin"

    def test_onsite_with_none_location_triggers(self):
        # Cannot verify compatibility — safer to reject unknown onsite locations
        job = _job(remote_type="onsite", location=None)
        result = check_hard_filters(job, _config())
        assert result.triggered is True
        assert result.reason == "onsite_unknown_location"


class TestHybridRejection:
    def test_hybrid_triggers_when_reject_hybrid_true(self):
        job = _job(remote_type="hybrid")
        result = check_hard_filters(job, _config(reject_hybrid=True))
        assert result.triggered is True
        assert result.reason == "hybrid_rejected"

    def test_hybrid_does_not_trigger_when_reject_hybrid_false(self):
        job = _job(remote_type="hybrid")
        result = check_hard_filters(job, _config(reject_hybrid=False))
        assert result.triggered is False

    def test_remote_not_affected(self):
        job = _job(remote_type="remote")
        result = check_hard_filters(job, _config(reject_hybrid=True))
        assert result.triggered is False


class TestUsTerritoryRestricted:
    def test_us_location_triggers(self):
        job = _job(location="New York, United States")
        result = check_hard_filters(job, _config())
        assert result.triggered is True
        assert result.reason == "us_territory_restricted"

    def test_us_work_auth_in_description_triggers(self):
        job = _job(description="Must be authorized to work in the United States")
        result = check_hard_filters(job, _config())
        assert result.triggered is True
        assert result.reason == "us_work_authorization_required"

    def test_eu_location_does_not_trigger(self):
        job = _job(location="Warsaw, Poland")
        result = check_hard_filters(job, _config())
        assert result.triggered is False

    def test_none_location_does_not_trigger(self):
        job = _job(location=None)
        result = check_hard_filters(job, _config())
        assert result.triggered is False


class TestRateFloor:
    def test_eur_below_day_floor_triggers(self):
        job = _job(salary_min=250.0, salary_currency="EUR", salary_period="day")
        result = check_hard_filters(job, _config())
        assert result.triggered is True
        assert result.reason == "rate_below_floor_250eur_day"

    def test_eur_at_day_floor_does_not_trigger(self):
        job = _job(salary_min=320.0, salary_currency="EUR", salary_period="day")
        result = check_hard_filters(job, _config())
        assert result.triggered is False

    def test_eur_hourly_below_floor_triggers(self):
        job = _job(salary_min=30.0, salary_currency="EUR", salary_period="hour")
        result = check_hard_filters(job, _config())
        assert result.triggered is True
        assert result.reason == "rate_below_floor_30eur_hour"

    def test_usd_currency_does_not_trigger_yet(self):
        job = _job(salary_min=10.0, salary_currency="USD", salary_period="day")
        result = check_hard_filters(job, _config())
        assert result.triggered is False

    def test_missing_salary_does_not_trigger(self):
        job = _job(salary_min=None, salary_currency=None, salary_period=None)
        result = check_hard_filters(job, _config())
        assert result.triggered is False


class TestPriorityOrder:
    def test_eu_citizenship_takes_priority_over_rate(self):
        job = _job(
            description="EU citizenship required",
            salary_min=100.0,
            salary_currency="EUR",
            salary_period="day",
        )
        result = check_hard_filters(job, _config())
        assert result.reason == "eu_citizenship_required"
