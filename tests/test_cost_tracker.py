"""Tests for cost tracker."""

from pathlib import Path

from job_matcher.cost_tracker import CostTracker
from job_matcher.models import CostLedgerEntry
from job_matcher.storage import JsonStore


def _make_tracker(tmp_path: Path, monkeypatch) -> CostTracker:
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    store = JsonStore(
        file_path=tmp_path / "cost_ledger.json",
        model=CostLedgerEntry,
        lock_dir=lock_dir,
    )
    monkeypatch.setattr("job_matcher.cost_tracker.cost_store", store)
    return CostTracker()


class TestRecord:
    def test_appends_to_ledger(self, tmp_path: Path, monkeypatch):
        tracker = _make_tracker(tmp_path, monkeypatch)
        tracker.record("score", "keyword_extraction", 1500, 150, job_id="abc")
        tracker.record("score", "semantic_scoring", 1500, 200, job_id="abc", cv_id="cv1")
        store = JsonStore(
            file_path=tmp_path / "cost_ledger.json",
            model=CostLedgerEntry,
            lock_dir=tmp_path / "locks",
        )
        assert store.count() == 2

    def test_computes_cost_from_tokens_and_model(self, tmp_path: Path, monkeypatch):
        tracker = _make_tracker(tmp_path, monkeypatch)
        entry = tracker.record("score", "keyword_extraction", 1000, 100)
        # Haiku: $1/M input, $5/M output
        expected = 1000 * 1.0 / 1_000_000 + 100 * 5.0 / 1_000_000
        assert entry.cost_usd == round(expected, 6)

    def test_increments_id(self, tmp_path: Path, monkeypatch):
        tracker = _make_tracker(tmp_path, monkeypatch)
        e1 = tracker.record("score", "keyword_extraction", 100, 10)
        e2 = tracker.record("score", "semantic_scoring", 100, 10)
        assert e2.id == e1.id + 1


class TestEstimate:
    def test_estimate_scoring_run_accuracy(self, tmp_path: Path, monkeypatch):
        tracker = _make_tracker(tmp_path, monkeypatch)
        estimate = tracker.estimate_scoring_run(
            num_jobs=10, num_cvs=7, include_keyword_extraction=True
        )
        # 10 keyword calls + 70 scoring calls = 80 total
        assert estimate.estimated_calls == 80
        assert estimate.estimated_cost_usd > 0

    def test_estimate_without_keyword_extraction(self, tmp_path: Path, monkeypatch):
        tracker = _make_tracker(tmp_path, monkeypatch)
        estimate = tracker.estimate_scoring_run(
            num_jobs=10, num_cvs=7, include_keyword_extraction=False
        )
        assert estimate.estimated_calls == 70


class TestAggregates:
    def test_summary_by_operation(self, tmp_path: Path, monkeypatch):
        tracker = _make_tracker(tmp_path, monkeypatch)
        tracker.record("score", "keyword_extraction", 1000, 100)
        tracker.record("score", "keyword_extraction", 1000, 100)
        tracker.record("score", "semantic_scoring", 1500, 200)
        summary = tracker.summary_by_operation()
        assert "keyword_extraction" in summary
        assert "semantic_scoring" in summary
        assert summary["keyword_extraction"] > summary["semantic_scoring"]
