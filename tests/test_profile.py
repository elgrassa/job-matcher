"""Tests for profile management and migration."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from job_matcher import profile


@pytest.fixture(autouse=True)
def _reset_profile():
    """Reset profile to default after each test."""
    profile.set_profile("default")
    yield
    profile.set_profile("default")


def test_set_and_get_profile():
    profile.set_profile("wife")
    assert profile.get_profile() == "wife"


def test_default_profile():
    assert profile.get_profile() == "default"


def test_profile_data_dir_creates_dirs(tmp_path: Path):
    profiles_dir = tmp_path / "profiles"
    with patch.object(profile, "PROFILES_DIR", profiles_dir):
        d = profile.profile_data_dir("test_user")
    assert d == profiles_dir / "test_user"
    assert d.exists()
    assert (d / ".locks").exists()


def test_migrate_flat_to_profiles(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    profiles_dir = data_dir / "profiles"

    # Create fake flat files
    for name in profile._PROFILE_FILES:
        (data_dir / name).write_text(json.dumps({"test": name}))

    with (
        patch.object(profile, "DATA_DIR", data_dir),
        patch.object(profile, "PROFILES_DIR", profiles_dir),
    ):
        result = profile.migrate_flat_to_profiles()

    assert result is True
    default_dir = profiles_dir / "default"
    assert default_dir.exists()
    for name in profile._PROFILE_FILES:
        assert (default_dir / name).exists()
        assert not (data_dir / name).exists()


def test_migrate_idempotent(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    profiles_dir = data_dir / "profiles"
    (profiles_dir / "default").mkdir(parents=True)

    with (
        patch.object(profile, "DATA_DIR", data_dir),
        patch.object(profile, "PROFILES_DIR", profiles_dir),
    ):
        result = profile.migrate_flat_to_profiles()

    assert result is False
