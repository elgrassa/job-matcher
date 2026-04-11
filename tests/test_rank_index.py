"""Tests for rank index persistence."""

from pathlib import Path
from unittest.mock import patch

from job_matcher import rank_index


def test_save_and_resolve(tmp_path: Path):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    with patch.object(rank_index, "profile_data_dir", return_value=profile_dir):
        rank_index.save_rank_index([("job1", "cv_a"), ("job2", "cv_b")])
        assert rank_index.resolve_ref("1") == ("job1", "cv_a")
        assert rank_index.resolve_ref("2") == ("job2", "cv_b")


def test_resolve_out_of_range(tmp_path: Path):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    with patch.object(rank_index, "profile_data_dir", return_value=profile_dir):
        rank_index.save_rank_index([("job1", "cv_a")])
        assert rank_index.resolve_ref("5") is None


def test_resolve_non_digit():
    assert rank_index.resolve_ref("abc") is None
    assert rank_index.resolve_ref("job123") is None


def test_resolve_no_index_file(tmp_path: Path):
    profile_dir = tmp_path / "empty"
    profile_dir.mkdir()
    with patch.object(rank_index, "profile_data_dir", return_value=profile_dir):
        assert rank_index.resolve_ref("1") is None
