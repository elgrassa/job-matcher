"""Tests for Pydantic model validation."""

import pytest
from pydantic import ValidationError

from job_matcher.models import (
    Application,
    ApplicationStatus,
    CostLedgerEntry,
    CvVersion,
    JdKeywords,
    Job,
    JobSource,
    MatchScore,
    RawJob,
    ScrapeRun,
)

TS = "2026-04-10T10:00:00+00:00"


def _job(**overrides) -> dict:
    base = {
        "id": "a3f7c2b8e1d94f56",
        "title": "Senior SDET",
        "company": "Acme",
        "location": "Wroclaw",
        "description": "Test description.",
        "salary_min": 320.0,
        "salary_max": 480.0,
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
    return base


class TestJob:
    def test_valid_job_creates(self):
        job = Job(**_job())
        assert job.id == "a3f7c2b8e1d94f56"

    def test_requires_utc_datetimes(self):
        with pytest.raises(ValidationError, match="timezone-aware"):
            Job(**_job(first_seen_at="2026-04-10T10:00:00"))

    def test_salary_max_ge_min_validator(self):
        with pytest.raises(ValidationError, match="salary_max"):
            Job(**_job(salary_min=500.0, salary_max=300.0))

    def test_salary_max_equal_to_min_ok(self):
        job = Job(**_job(salary_min=400.0, salary_max=400.0))
        assert job.salary_max == 400.0

    def test_null_salary_ok(self):
        job = Job(
            **_job(salary_min=None, salary_max=None, salary_currency=None, salary_period=None)
        )
        assert job.salary_min is None

    def test_null_posted_at_ok(self):
        job = Job(**_job(posted_at=None))
        assert job.posted_at is None

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError, match="Extra inputs"):
            Job(**_job(extra_field="nope"))


class TestJobSource:
    def test_valid_source(self):
        src = JobSource(
            job_id="abc123",
            platform="linkedin",
            platform_job_id="12345",
            url="https://linkedin.com/jobs/view/12345",
            scraped_at=TS,
            raw={"key": "value"},
        )
        assert src.platform == "linkedin"

    def test_url_must_be_http(self):
        with pytest.raises(ValidationError, match="http"):
            JobSource(
                job_id="abc",
                platform="linkedin",
                platform_job_id=None,
                url="ftp://bad.com/job",
                scraped_at=TS,
                raw={},
            )


class TestCvVersion:
    def test_valid_cv(self):
        cv = CvVersion(
            id="senior_sdet",
            name="Senior SDET",
            file_path="cvs/senior_sdet.md",
            content_hash="sha256:" + "a" * 64,
            content="CV content here.",
            char_count=16,
            loaded_at=TS,
        )
        assert cv.enabled is True

    def test_id_must_be_snake_case(self):
        with pytest.raises(ValidationError, match="snake_case"):
            CvVersion(
                id="Senior-SDET",
                name="Test",
                file_path="test.md",
                content_hash="sha256:" + "a" * 64,
                content="x",
                char_count=1,
                loaded_at=TS,
            )

    def test_hash_format_validator(self):
        with pytest.raises(ValidationError, match="sha256"):
            CvVersion(
                id="test",
                name="Test",
                file_path="test.md",
                content_hash="md5:short",
                content="x",
                char_count=1,
                loaded_at=TS,
            )


class TestJdKeywords:
    def test_normalize_keywords(self):
        kw = JdKeywords(
            job_id="abc",
            must_have=["Java", "java", " Python ", ""],
            nice_to_have=["Cypress"],
            extracted_at=TS,
            job_description_hash="abc123",
        )
        assert kw.must_have == ["java", "python"]
        assert kw.nice_to_have == ["cypress"]


class TestMatchScore:
    def test_score_in_range_validator(self):
        with pytest.raises(ValidationError, match="score must be in"):
            MatchScore(
                job_id="a",
                cv_id="b",
                keyword_score=1.5,
                keywords_required=[],
                keywords_matched=[],
                keywords_missing=[],
                semantic_score=0.5,
                reasoning="test",
                green_flags=[],
                red_flags=[],
                llm_model_used="test",
                final_score=0.5,
                hard_filter_triggered=None,
                scored_at=TS,
                cv_content_hash="abc",
                jd_keyword_hash="def",
            )

    def test_score_rounds_to_4_decimals(self):
        score = MatchScore(
            job_id="a",
            cv_id="b",
            keyword_score=0.33333333,
            keywords_required=[],
            keywords_matched=[],
            keywords_missing=[],
            semantic_score=0.66666666,
            reasoning="test",
            green_flags=[],
            red_flags=[],
            llm_model_used="test",
            final_score=0.55555555,
            hard_filter_triggered=None,
            scored_at=TS,
            cv_content_hash="abc",
            jd_keyword_hash="def",
        )
        assert score.keyword_score == 0.3333
        assert score.semantic_score == 0.6667
        assert score.final_score == 0.5556

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            MatchScore(
                job_id="a",
                cv_id="b",
                keyword_score=0.5,
                keywords_required=[],
                keywords_matched=[],
                keywords_missing=[],
                semantic_score=0.5,
                reasoning="test",
                green_flags=[],
                red_flags=[],
                llm_model_used="test",
                final_score=0.5,
                hard_filter_triggered=None,
                scored_at=TS,
                cv_content_hash="abc",
                jd_keyword_hash="def",
                extra="bad",
            )


class TestApplicationStatus:
    def test_enum_values(self):
        assert ApplicationStatus.SAVED == "saved"
        assert ApplicationStatus.APPLIED == "applied"
        assert ApplicationStatus.SCREENING == "screening"
        assert ApplicationStatus.INTERVIEW == "interview"
        assert ApplicationStatus.OFFER == "offer"
        assert ApplicationStatus.REJECTED == "rejected"
        assert ApplicationStatus.WITHDRAWN == "withdrawn"
        assert ApplicationStatus.GHOSTED == "ghosted"

    def test_all_statuses_count(self):
        assert len(ApplicationStatus) == 8


class TestApplication:
    def test_valid_application(self):
        app = Application(
            id=1,
            job_id="abc",
            cv_id="senior_sdet",
            status=ApplicationStatus.APPLIED,
            saved_at=None,
            applied_at=TS,
            last_status_change_at=TS,
        )
        assert app.notes == ""
        assert app.status_history == []


class TestCostLedgerEntry:
    def test_valid_entry(self):
        entry = CostLedgerEntry(
            id=1,
            timestamp=TS,
            command="score",
            operation="semantic_scoring",
            job_id="abc",
            cv_id="senior_sdet",
            model="claude-haiku-4-5-20251001",
            input_tokens=1500,
            output_tokens=200,
            cost_usd=0.0025,
        )
        assert entry.cost_usd == 0.0025

    def test_negative_tokens_rejected(self):
        with pytest.raises(ValidationError):
            CostLedgerEntry(
                id=1,
                timestamp=TS,
                command="score",
                operation="semantic_scoring",
                job_id=None,
                cv_id=None,
                model="test",
                input_tokens=-1,
                output_tokens=0,
                cost_usd=0.0,
            )

    def test_negative_cost_rejected(self):
        with pytest.raises(ValidationError):
            CostLedgerEntry(
                id=1,
                timestamp=TS,
                command="score",
                operation="semantic_scoring",
                job_id=None,
                cv_id=None,
                model="test",
                input_tokens=0,
                output_tokens=0,
                cost_usd=-0.01,
            )


class TestRawJob:
    def test_valid_raw_job(self):
        raw = RawJob(
            platform="linkedin",
            platform_job_id="12345",
            url="https://linkedin.com/jobs/view/12345",
            title="Senior SDET",
            company="Acme",
            location="Wroclaw",
            description="Test",
            salary_raw="300-480 EUR/day",
            employment_type_raw="B2B",
            remote_type_raw="Remote",
            posted_at_raw="2026-04-10",
            raw={"full": "data"},
        )
        assert raw.platform == "linkedin"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            RawJob(
                platform="linkedin",
                platform_job_id=None,
                url="https://test.com",
                title="Test",
                company="Test",
                location=None,
                description="Test",
                salary_raw=None,
                employment_type_raw=None,
                remote_type_raw=None,
                posted_at_raw=None,
                raw={},
                bonus="bad",
            )


class TestScrapeRun:
    def test_valid_scrape_run(self):
        run = ScrapeRun(
            id="run_001",
            initiated_at=TS,
            initiated_by="user_cli",
            platform="linkedin",
            jobs_fetched=47,
            cache_hit=False,
            duration_seconds=12.5,
        )
        assert run.platform == "linkedin"
        assert run.initiated_by == "user_cli"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ScrapeRun(
                id="run_001",
                initiated_at=TS,
                platform="linkedin",
                jobs_fetched=10,
                duration_seconds=1.0,
                extra_field="bad",
            )


class TestCvVersionHashValidation:
    def test_non_hex_chars_rejected(self):
        with pytest.raises(ValidationError, match="hex"):
            CvVersion(
                id="test",
                name="Test",
                file_path="test.md",
                content_hash="sha256:" + "z" * 64,
                content="x",
                char_count=1,
                loaded_at=TS,
            )

    def test_uppercase_hex_rejected(self):
        with pytest.raises(ValidationError, match="hex"):
            CvVersion(
                id="test",
                name="Test",
                file_path="test.md",
                content_hash="sha256:" + "A" * 64,
                content="x",
                char_count=1,
                loaded_at=TS,
            )


class TestJobRoundtrip:
    def test_dump_and_validate_produces_identical_job(self):
        job = Job(**_job())
        dumped = job.model_dump(mode="json")
        restored = Job.model_validate(dumped)
        assert job.id == restored.id
        assert job.title == restored.title
        assert job.salary_min == restored.salary_min
        assert job.first_seen_at == restored.first_seen_at
        assert job.posted_at == restored.posted_at

    def test_roundtrip_with_null_salary(self):
        job = Job(
            **_job(
                salary_min=None, salary_max=None,
                salary_currency=None, salary_period=None, posted_at=None,
            )
        )
        dumped = job.model_dump(mode="json")
        restored = Job.model_validate(dumped)
        assert restored.salary_min is None
        assert restored.posted_at is None

    def test_roundtrip_preserves_score_rounding(self):
        score = MatchScore(
            job_id="a", cv_id="b",
            keyword_score=0.33333, semantic_score=0.66666,
            keywords_required=[], keywords_matched=[], keywords_missing=[],
            reasoning="test", green_flags=[], red_flags=[],
            llm_model_used="test", final_score=0.55555,
            hard_filter_triggered=None, scored_at=TS,
            cv_content_hash="abc", jd_keyword_hash="def",
        )
        dumped = score.model_dump(mode="json")
        restored = MatchScore.model_validate(dumped)
        assert restored.keyword_score == score.keyword_score
        assert restored.semantic_score == score.semantic_score


class TestJobIdValidation:
    def test_valid_hex_id(self):
        job = Job(**_job(id="a3f7c2b8e1d94f56"))
        assert job.id == "a3f7c2b8e1d94f56"

    def test_rejects_non_hex(self):
        with pytest.raises(ValidationError, match="16 lowercase hex"):
            Job(**_job(id="not-a-valid-id!!"))

    def test_rejects_wrong_length(self):
        with pytest.raises(ValidationError, match="16 lowercase hex"):
            Job(**_job(id="abc"))

    def test_rejects_uppercase(self):
        with pytest.raises(ValidationError, match="16 lowercase hex"):
            Job(**_job(id="A3F7C2B8E1D94F56"))


class TestMatchScoreKeywordConsistency:
    def test_consistent_keywords_ok(self):
        score = MatchScore(
            job_id="a", cv_id="b",
            keyword_score=0.5, semantic_score=0.5, final_score=0.5,
            keywords_required=["java", "python"],
            keywords_matched=["java"],
            keywords_missing=["python"],
            reasoning="test", green_flags=[], red_flags=[],
            llm_model_used="test", hard_filter_triggered=None,
            scored_at=TS, cv_content_hash="abc", jd_keyword_hash="def",
        )
        assert score.keywords_matched == ["java"]

    def test_extra_in_matched_rejected(self):
        with pytest.raises(ValidationError, match=r"matched.*missing.*required"):
            MatchScore(
                job_id="a", cv_id="b",
                keyword_score=0.5, semantic_score=0.5, final_score=0.5,
                keywords_required=["java"],
                keywords_matched=["java", "python"],
                keywords_missing=[],
                reasoning="test", green_flags=[], red_flags=[],
                llm_model_used="test", hard_filter_triggered=None,
                scored_at=TS, cv_content_hash="abc", jd_keyword_hash="def",
            )

    def test_keyword_in_both_matched_and_missing_rejected(self):
        with pytest.raises(ValidationError, match="both matched and missing"):
            MatchScore(
                job_id="a", cv_id="b",
                keyword_score=0.5, semantic_score=0.5, final_score=0.5,
                keywords_required=["java"],
                keywords_matched=["java"],
                keywords_missing=["java"],
                reasoning="test", green_flags=[], red_flags=[],
                llm_model_used="test", hard_filter_triggered=None,
                scored_at=TS, cv_content_hash="abc", jd_keyword_hash="def",
            )
