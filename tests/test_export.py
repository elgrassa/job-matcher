"""Tests for CSV export."""

import csv
from datetime import UTC, datetime
from pathlib import Path

from job_matcher.export import export_rank_csv
from job_matcher.models import Job, MatchScore

TS = "2026-04-10T10:00:00+00:00"


def _score(**overrides) -> MatchScore:
    base = {
        "job_id": "j1",
        "cv_id": "cv_a",
        "keyword_score": 0.8,
        "keywords_required": ["java"],
        "keywords_matched": ["java"],
        "keywords_missing": [],
        "semantic_score": 0.7,
        "reasoning": "Good",
        "green_flags": [],
        "red_flags": [],
        "llm_model_used": "test",
        "final_score": 0.75,
        "hard_filter_triggered": None,
        "scored_at": datetime.now(UTC),
        "cv_content_hash": "abc",
        "jd_keyword_hash": "def",
    }
    base.update(overrides)
    return MatchScore(**base)


def _job(**overrides) -> Job:
    base = {
        "id": "a3f7c2b8e1d94f56",
        "title": "SDET",
        "company": "Acme",
        "location": "Remote",
        "description": "desc",
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


JID1 = "a3f7c2b8e1d94f56"
JID2 = "b4e8d3c9f2a05e67"


def test_export_csv_basic(tmp_path: Path):
    scores = [_score(job_id=JID1, final_score=0.8), _score(job_id=JID2, final_score=0.6)]
    jobs = {JID1: _job(id=JID1, title="SDET"), JID2: _job(id=JID2, title="Dev")}
    path = tmp_path / "out.csv"

    count = export_rank_csv(path, scores, jobs, {JID1: "http://example.com"}, {})
    assert count == 2

    with open(path) as f:
        reader = list(csv.reader(f))
    assert reader[0][0] == "Rank"  # header
    assert len(reader) == 3  # header + 2 rows
    assert reader[1][5] == "SDET"


def test_export_csv_empty(tmp_path: Path):
    path = tmp_path / "empty.csv"
    count = export_rank_csv(path, [], {}, {}, {})
    assert count == 0
