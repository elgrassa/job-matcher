"""Tests for dedup module — written first (TDD per spec)."""

import pytest

from job_matcher.dedup import (
    SalaryInfo,
    canonicalize_raw,
    compute_canonical_id,
    map_employment_type,
    map_remote_type,
    normalize_company,
    normalize_location,
    normalize_title,
    parse_salary,
)
from job_matcher.models import RawJob


class TestNormalizeTitle:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Senior SDET", "sdet"),
            ("Sr. SDET", "sdet"),
            ("Sr SDET", "sdet"),
            ("Junior SDET", "sdet"),
            ("Jr. SDET", "sdet"),
            ("Senior SDET (m/f/d)", "sdet"),
            ("Senior SDET (f/m/d)", "sdet"),
            ("Senior SDET (m/w/d)", "sdet"),
            ("Senior SDET (d/w/m)", "sdet"),
            ("Senior Software Engineer (f/m/d) - Remote", "software engineer"),
            ("SDET - Backend", "sdet backend"),
            ("Senior QA Automation Engineer [Remote]", "qa automation engineer"),
            ("QA Engineer (Remote)", "qa engineer"),
            ("Lead QA - Hybrid", "lead qa"),
            ("", ""),
        ],
    )
    def test_normalize(self, raw: str, expected: str):
        assert normalize_title(raw) == expected


class TestNormalizeCompany:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Acme Sp. z o.o.", "acme"),
            ("Acme sp. z o.o. sp. k.", "acme"),
            ("Noumena Digital AG", "noumena digital"),
            ("UBS", "ubs"),
            ("Deutsche Bank GmbH", "deutsche bank"),
            ("Some Corp.", "some"),
            ("Some Corp", "some"),
            ("Alpha Ltd.", "alpha"),
            ("Alpha Ltd", "alpha"),
            ("Beta LLC", "beta"),
            ("Gamma Inc.", "gamma"),
            ("Gamma Inc", "gamma"),
            ("Delta B.V.", "delta"),
            ("Delta BV", "delta"),
            ("Epsilon N.V.", "epsilon"),
            ("Zeta S.A.", "zeta"),
            ("Eta S.R.L.", "eta"),
            ("", ""),
        ],
    )
    def test_normalize(self, raw: str, expected: str):
        assert normalize_company(raw) == expected


class TestNormalizeLocation:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Wrocław, Poland", "wrocław"),
            ("Wroclaw, Poland", "wroclaw"),
            ("Berlin, Germany", "berlin"),
            ("London SW1A 1AA, United Kingdom", "london"),
            ("Zurich 8001, Switzerland", "zurich"),
            (None, ""),
            ("Remote", "remote"),
            ("", ""),
        ],
    )
    def test_normalize(self, raw: str | None, expected: str):
        assert normalize_location(raw) == expected


class TestCanonicalId:
    def test_same_job_same_id(self):
        id1 = compute_canonical_id("Senior SDET", "Acme Corp", "Wroclaw, Poland")
        id2 = compute_canonical_id("Senior SDET", "Acme Corp", "Wroclaw, Poland")
        assert id1 == id2

    def test_different_title_different_id(self):
        id1 = compute_canonical_id("Senior SDET", "Acme Corp", "Wroclaw")
        id2 = compute_canonical_id("QA Lead", "Acme Corp", "Wroclaw")
        assert id1 != id2

    def test_case_variation_same_id(self):
        id1 = compute_canonical_id("Senior SDET", "Acme Corp", "Wroclaw")
        id2 = compute_canonical_id("senior sdet", "acme corp", "wroclaw")
        assert id1 == id2

    def test_seniority_marker_variation_same_id(self):
        id1 = compute_canonical_id("Senior SDET", "Acme", "Wroclaw")
        id2 = compute_canonical_id("Sr. SDET", "Acme", "Wroclaw")
        assert id1 == id2

    def test_legal_suffix_variation_same_id(self):
        id1 = compute_canonical_id("SDET", "Acme Sp. z o.o.", "Wroclaw")
        id2 = compute_canonical_id("SDET", "Acme", "Wroclaw")
        assert id1 == id2

    def test_id_format(self):
        cid = compute_canonical_id("SDET", "Acme", "Wroclaw")
        assert len(cid) == 16
        assert all(c in "0123456789abcdef" for c in cid)

    def test_empty_inputs_still_deterministic(self):
        id1 = compute_canonical_id("", "", None)
        id2 = compute_canonical_id("", "", None)
        assert id1 == id2
        assert len(id1) == 16


class TestParseSalary:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (
                "300-480 EUR/day",
                SalaryInfo(min=300.0, max=480.0, currency="EUR", period="day"),
            ),
            (
                "€50/h",
                SalaryInfo(min=50.0, max=None, currency="EUR", period="hour"),
            ),
            (
                "USD 120,000 - 180,000 / year",
                SalaryInfo(min=120000.0, max=180000.0, currency="USD", period="year"),
            ),
            (
                "15k-25k PLN/month",
                SalaryInfo(min=15000.0, max=25000.0, currency="PLN", period="month"),
            ),
            (
                None,
                SalaryInfo(min=None, max=None, currency=None, period=None),
            ),
            (
                "Competitive",
                SalaryInfo(min=None, max=None, currency=None, period=None),
            ),
            (
                "300 - 480 EUR / day",
                SalaryInfo(min=300.0, max=480.0, currency="EUR", period="day"),
            ),
            (
                "40-60 CHF/hour",
                SalaryInfo(min=40.0, max=60.0, currency="CHF", period="hour"),
            ),
            (
                "£400/day",
                SalaryInfo(min=400.0, max=None, currency="GBP", period="day"),
            ),
        ],
    )
    def test_parse(self, raw: str | None, expected: SalaryInfo):
        assert parse_salary(raw) == expected


class TestMapEmploymentType:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("B2B", "b2b"),
            ("b2b", "b2b"),
            ("Permanent", "permanent"),
            ("permanent", "permanent"),
            ("Contract", "contract"),
            ("contract", "contract"),
            ("Internship", "internship"),
            (None, "unknown"),
            ("something weird", "unknown"),
        ],
    )
    def test_map(self, raw: str | None, expected: str):
        assert map_employment_type(raw) == expected


class TestMapRemoteType:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Remote", "remote"),
            ("remote", "remote"),
            ("Hybrid", "hybrid"),
            ("hybrid", "hybrid"),
            ("Onsite", "onsite"),
            ("On-site", "onsite"),
            ("on_site", "onsite"),
            (None, "unknown"),
            ("something weird", "unknown"),
        ],
    )
    def test_map(self, raw: str | None, expected: str):
        assert map_remote_type(raw) == expected


class TestCanonicalizeRaw:
    def test_produces_matching_job_and_source(self):
        from datetime import UTC, datetime

        raw = RawJob(
            platform="linkedin",
            platform_job_id="12345",
            url="https://linkedin.com/jobs/view/12345",
            title="Senior SDET",
            company="Acme Corp",
            location="Wroclaw, Poland",
            description="Java, Python, CI/CD.",
            salary_raw="300-480 EUR/day",
            employment_type_raw="B2B",
            remote_type_raw="Remote",
            posted_at_raw="2026-04-10",
            raw={"id": "12345"},
        )
        now = datetime(2026, 4, 10, 12, 0, 0, tzinfo=UTC)
        job, source = canonicalize_raw(raw, now)

        assert job.id == source.job_id
        assert job.title == "Senior SDET"
        assert job.company == "Acme Corp"
        assert job.salary_min == 300.0
        assert job.salary_max == 480.0
        assert job.employment_type == "b2b"
        assert job.remote_type == "remote"

        assert source.platform == "linkedin"
        assert source.url == "https://linkedin.com/jobs/view/12345"
        assert source.raw == {"id": "12345"}

    def test_sets_all_timestamps_to_now(self):
        from datetime import UTC, datetime

        raw = RawJob(
            platform="justjoin",
            platform_job_id=None,
            url="https://justjoin.it/offers/test",
            title="QA",
            company="Test",
            location=None,
            description="Short.",
            salary_raw=None,
            employment_type_raw=None,
            remote_type_raw=None,
            posted_at_raw=None,
            raw={},
        )
        now = datetime(2026, 4, 10, 14, 30, 0, tzinfo=UTC)
        job, source = canonicalize_raw(raw, now)

        assert job.first_seen_at == now
        assert job.last_seen_at == now
        assert job.scraped_at == now
        assert source.scraped_at == now

    def test_preserves_raw_in_source(self):
        from datetime import UTC, datetime

        raw_data = {"full": "actor output", "nested": {"key": "value"}}
        raw = RawJob(
            platform="nofluffjobs",
            platform_job_id="nfj-123",
            url="https://nofluffjobs.com/job/test",
            title="SDET",
            company="Co",
            location="Remote",
            description="Test",
            salary_raw=None,
            employment_type_raw=None,
            remote_type_raw=None,
            posted_at_raw=None,
            raw=raw_data,
        )
        _, source = canonicalize_raw(raw, datetime(2026, 4, 10, tzinfo=UTC))
        assert source.raw == raw_data
