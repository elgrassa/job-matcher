"""Tests for application tracker."""

from pathlib import Path

from job_matcher.config import WarningConfig
from job_matcher.models import Application, ApplicationStatus, MatchScore
from job_matcher.storage import JsonStore


def _make_stores(tmp_path: Path, monkeypatch):
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    app_store = JsonStore(
        file_path=tmp_path / "apps.json", model=Application, lock_dir=lock_dir
    )
    score_store = JsonStore(
        file_path=tmp_path / "scores.json", model=MatchScore, lock_dir=lock_dir
    )
    monkeypatch.setattr("job_matcher.tracker.applications_store", app_store)
    monkeypatch.setattr("job_matcher.tracker.scores_store", score_store)
    return app_store, score_store


TS = "2026-04-10T10:00:00+00:00"


class TestSaveJob:
    def test_creates_application(self, tmp_path, monkeypatch):
        app_store, _ = _make_stores(tmp_path, monkeypatch)
        from job_matcher.tracker import save_job

        app = save_job("abc123def4567890", "senior_sdet")
        assert app.status == ApplicationStatus.SAVED
        assert app.job_id == "abc123def4567890"
        assert app_store.count() == 1

    def test_increments_id(self, tmp_path, monkeypatch):
        _make_stores(tmp_path, monkeypatch)
        from job_matcher.tracker import save_job

        a1 = save_job("abc123def4567890", "senior_sdet")
        a2 = save_job("bbb123def4567890", "ai_engineer")
        assert a2.id == a1.id + 1


class TestApplyToJob:
    def test_creates_new_application(self, tmp_path, monkeypatch):
        _make_stores(tmp_path, monkeypatch)
        from job_matcher.tracker import apply_to_job

        app = apply_to_job("abc123def4567890", "senior_sdet")
        assert app.status == ApplicationStatus.APPLIED
        assert app.applied_at is not None

    def test_updates_saved_to_applied(self, tmp_path, monkeypatch):
        _make_stores(tmp_path, monkeypatch)
        from job_matcher.tracker import apply_to_job, save_job

        saved = save_job("abc123def4567890", "senior_sdet")
        applied = apply_to_job("abc123def4567890", "senior_sdet")
        assert applied.id == saved.id
        assert applied.status == ApplicationStatus.APPLIED
        assert len(applied.status_history) == 2


class TestUpdateStatus:
    def test_updates_existing(self, tmp_path, monkeypatch):
        _make_stores(tmp_path, monkeypatch)
        from job_matcher.tracker import apply_to_job, update_status

        apply_to_job("abc123def4567890", "senior_sdet")
        app = update_status("abc123def4567890", "senior_sdet", ApplicationStatus.INTERVIEW)
        assert app is not None
        assert app.status == ApplicationStatus.INTERVIEW

    def test_returns_none_for_missing(self, tmp_path, monkeypatch):
        _make_stores(tmp_path, monkeypatch)
        from job_matcher.tracker import update_status

        result = update_status("nonexistent0000", "cv", ApplicationStatus.REJECTED)
        assert result is None


class TestGreyOut:
    def test_greyed_out_when_applied(self, tmp_path, monkeypatch):
        _make_stores(tmp_path, monkeypatch)
        from job_matcher.tracker import apply_to_job, is_greyed_out

        apply_to_job("abc123def4567890", "senior_sdet")
        assert is_greyed_out("abc123def4567890") is True

    def test_not_greyed_out_when_only_saved(self, tmp_path, monkeypatch):
        _make_stores(tmp_path, monkeypatch)
        from job_matcher.tracker import is_greyed_out, save_job

        save_job("abc123def4567890", "senior_sdet")
        assert is_greyed_out("abc123def4567890") is False

    def test_get_applied_cv(self, tmp_path, monkeypatch):
        _make_stores(tmp_path, monkeypatch)
        from job_matcher.tracker import apply_to_job, get_applied_cv

        apply_to_job("abc123def4567890", "senior_sdet")
        assert get_applied_cv("abc123def4567890") == "senior_sdet"

    def test_withdrawn_is_not_greyed_out(self, tmp_path, monkeypatch):
        _make_stores(tmp_path, monkeypatch)
        from job_matcher.tracker import apply_to_job, is_greyed_out, update_status

        apply_to_job("abc123def4567890", "senior_sdet")
        assert is_greyed_out("abc123def4567890") is True
        update_status("abc123def4567890", "senior_sdet", ApplicationStatus.WITHDRAWN)
        assert is_greyed_out("abc123def4567890") is False

    def test_get_applied_cv_returns_none_when_no_apps(self, tmp_path, monkeypatch):
        _make_stores(tmp_path, monkeypatch)
        from job_matcher.tracker import get_applied_cv

        assert get_applied_cv("nonexistent0000") is None


class TestApplyWarnings:
    def _score(self, job_id, cv_id, final, kw):
        import hashlib

        return MatchScore(
            job_id=job_id,
            cv_id=cv_id,
            keyword_score=kw,
            keywords_required=["java"],
            keywords_matched=["java"] if kw > 0 else [],
            keywords_missing=[] if kw > 0 else ["java"],
            semantic_score=final - kw * 0.35,
            reasoning="test",
            green_flags=[],
            red_flags=[],
            llm_model_used="test",
            final_score=final,
            hard_filter_triggered=None,
            scored_at=TS,
            cv_content_hash="sha256:" + "a" * 64,
            jd_keyword_hash=hashlib.sha256(b"java").hexdigest(),
        )

    def test_warns_when_better_cv_exists(self, tmp_path, monkeypatch):
        _, score_store = _make_stores(tmp_path, monkeypatch)
        from job_matcher.tracker import check_apply_warnings

        score_store.save_all([
            self._score("abc123def4567890", "senior_sdet", 0.60, 0.5),
            self._score("abc123def4567890", "ai_engineer", 0.85, 0.8),
        ])
        config = WarningConfig(score_delta_threshold=0.12)
        warnings = check_apply_warnings("abc123def4567890", "senior_sdet", config)
        assert len(warnings) == 1
        assert warnings[0].better_cv_id == "ai_engineer"

    def test_no_warning_when_chosen_is_best(self, tmp_path, monkeypatch):
        _, score_store = _make_stores(tmp_path, monkeypatch)
        from job_matcher.tracker import check_apply_warnings

        score_store.save_all([
            self._score("abc123def4567890", "senior_sdet", 0.85, 0.8),
            self._score("abc123def4567890", "ai_engineer", 0.60, 0.5),
        ])
        config = WarningConfig(score_delta_threshold=0.12)
        warnings = check_apply_warnings("abc123def4567890", "senior_sdet", config)
        assert len(warnings) == 0
