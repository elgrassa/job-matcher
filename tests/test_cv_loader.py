"""Tests for CV loader."""

from pathlib import Path

import pytest

from job_matcher.config import CvRegistryEntry, ScoringConfig
from job_matcher.cv_loader import (
    CvFileMissingError,
    CvRegistryMismatchError,
    compute_content_hash,
    load_all_registered_cvs,
    load_cv_file,
    sync_cvs_to_store,
)
from job_matcher.storage import JsonStore

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sample_cvs"


def _entry(
    cv_id: str = "test_cv",
    name: str = "Test CV",
    file: str = "test.md",
    enabled: bool = True,
) -> CvRegistryEntry:
    return CvRegistryEntry(id=cv_id, name=name, file=file, description="Test", enabled=enabled)


def _scoring_config(cvs: list[CvRegistryEntry], default: str = "test_cv") -> ScoringConfig:
    from job_matcher.config import HardFilterConfig, ScoringWeights, WarningConfig

    return ScoringConfig(
        weights=ScoringWeights(keyword=0.35, semantic=0.65),
        warning=WarningConfig(),
        hard_filters=HardFilterConfig(
            eu_citizenship_keywords=["eu citizenship required"],
            onsite_compatible_cities=["wroclaw"],
        ),
        cvs=cvs,
        default_cv=default,
    )


class TestComputeContentHash:
    def test_deterministic(self):
        h1 = compute_content_hash("hello world")
        h2 = compute_content_hash("hello world")
        assert h1 == h2

    def test_format(self):
        h = compute_content_hash("test")
        assert h.startswith("sha256:")
        assert len(h) == 71

    def test_sensitive_to_whitespace(self):
        h1 = compute_content_hash("hello")
        h2 = compute_content_hash("hello ")
        assert h1 != h2

    def test_different_content_different_hash(self):
        h1 = compute_content_hash("cv version A")
        h2 = compute_content_hash("cv version B")
        assert h1 != h2


class TestLoadCvFile:
    def test_reads_content_and_hashes(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("job_matcher.cv_loader.PROJECT_ROOT", tmp_path)
        cv_file = tmp_path / "cvs" / "test.md"
        cv_file.parent.mkdir(parents=True)
        cv_file.write_text("# Test CV\nJava, Python, 10 years", encoding="utf-8")

        entry = _entry(file="cvs/test.md")
        cv = load_cv_file(entry)
        assert cv.id == "test_cv"
        assert cv.content == "# Test CV\nJava, Python, 10 years"
        assert cv.char_count == len(cv.content)
        assert cv.content_hash == compute_content_hash(cv.content)
        assert cv.enabled is True

    def test_missing_enabled_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("job_matcher.cv_loader.PROJECT_ROOT", tmp_path)
        entry = _entry(file="cvs/nonexistent.md")
        with pytest.raises(CvFileMissingError):
            load_cv_file(entry)


class TestLoadAllRegisteredCvs:
    def test_loads_enabled_skips_disabled(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setattr("job_matcher.cv_loader.PROJECT_ROOT", tmp_path)
        cv_dir = tmp_path / "cvs"
        cv_dir.mkdir()
        (cv_dir / "a.md").write_text("CV A content")
        (cv_dir / "b.md").write_text("CV B content")

        config = _scoring_config(
            [
                _entry("cv_a", file="cvs/a.md", enabled=True),
                _entry("cv_b", file="cvs/b.md", enabled=False),
            ],
            default="cv_a",
        )
        results = load_all_registered_cvs(config)
        assert len(results) == 1
        assert results[0].id == "cv_a"

    def test_duplicate_ids_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("job_matcher.cv_loader.PROJECT_ROOT", tmp_path)
        config = _scoring_config(
            [_entry("same_id", file="a.md"), _entry("same_id", file="b.md")],
            default="same_id",
        )
        with pytest.raises(CvRegistryMismatchError, match="Duplicate"):
            load_all_registered_cvs(config)


class TestSyncCvsToStore:
    def _make_cv_store(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from job_matcher.models import CvVersion

        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        store = JsonStore(
            file_path=tmp_path / "cv_versions.json",
            model=CvVersion,
            lock_dir=lock_dir,
        )
        monkeypatch.setattr("job_matcher.cv_loader.cvs_store", store)
        return store

    def test_inserts_new_cvs(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("job_matcher.cv_loader.PROJECT_ROOT", tmp_path)
        store = self._make_cv_store(tmp_path, monkeypatch)

        cv_dir = tmp_path / "cvs"
        cv_dir.mkdir()
        (cv_dir / "a.md").write_text("CV A")

        config = _scoring_config([_entry("cv_a", file="cvs/a.md")], default="cv_a")
        result = sync_cvs_to_store(config)
        assert result.loaded == 1
        assert result.unchanged == 0
        assert store.count() == 1

    def test_skips_unchanged_cvs(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("job_matcher.cv_loader.PROJECT_ROOT", tmp_path)
        self._make_cv_store(tmp_path, monkeypatch)

        cv_dir = tmp_path / "cvs"
        cv_dir.mkdir()
        (cv_dir / "a.md").write_text("CV A")

        config = _scoring_config([_entry("cv_a", file="cvs/a.md")], default="cv_a")
        sync_cvs_to_store(config)
        result = sync_cvs_to_store(config)
        assert result.unchanged == 1
        assert result.loaded == 0
        assert result.updated == 0

    def test_updates_changed_cvs(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("job_matcher.cv_loader.PROJECT_ROOT", tmp_path)
        store = self._make_cv_store(tmp_path, monkeypatch)

        cv_dir = tmp_path / "cvs"
        cv_dir.mkdir()
        (cv_dir / "a.md").write_text("CV A version 1")

        config = _scoring_config([_entry("cv_a", file="cvs/a.md")], default="cv_a")
        sync_cvs_to_store(config)

        # Edit the CV file
        (cv_dir / "a.md").write_text("CV A version 2 with more keywords")
        result = sync_cvs_to_store(config)
        assert result.updated == 1
        assert result.unchanged == 0

        loaded = store.all()
        assert loaded[0].content == "CV A version 2 with more keywords"

    def test_disables_removed_cvs(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("job_matcher.cv_loader.PROJECT_ROOT", tmp_path)
        store = self._make_cv_store(tmp_path, monkeypatch)

        cv_dir = tmp_path / "cvs"
        cv_dir.mkdir()
        (cv_dir / "a.md").write_text("CV A")
        (cv_dir / "b.md").write_text("CV B")

        config_both = _scoring_config(
            [_entry("cv_a", file="cvs/a.md"), _entry("cv_b", file="cvs/b.md")],
            default="cv_a",
        )
        sync_cvs_to_store(config_both)
        assert store.count() == 2

        # Remove cv_b from config
        config_one = _scoring_config([_entry("cv_a", file="cvs/a.md")], default="cv_a")
        result = sync_cvs_to_store(config_one)
        assert result.disabled == 1

        cv_b = store.find_one(lambda c: c.id == "cv_b")
        assert cv_b is not None
        assert cv_b.enabled is False
