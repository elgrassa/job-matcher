"""Tests for config loading and validation."""

from pathlib import Path

import pytest
import yaml

from job_matcher.config import (
    ConfigFileNotFoundError,
    InvalidConfigError,
    ScoringWeights,
    load_platforms_config,
    load_scoring_config,
)


def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


def _minimal_scoring_yaml() -> dict:
    return {
        "scoring": {
            "weights": {"keyword": 0.35, "semantic": 0.65},
            "warning": {
                "score_delta_threshold": 0.12,
                "keyword_delta_threshold": 0.25,
            },
            "hard_filters": {
                "min_daily_rate_eur": 320,
                "min_hourly_rate_eur": 40,
                "eu_citizenship_keywords": ["eu citizenship required"],
                "onsite_compatible_cities": ["wroclaw"],
            },
        },
        "cvs": {
            "default": "test_cv",
            "versions": [
                {
                    "id": "test_cv",
                    "name": "Test CV",
                    "file": "cvs/test.md",
                    "description": "Test CV",
                }
            ],
        },
    }


def _minimal_platforms_yaml() -> dict:
    return {
        "platforms": {
            "linkedin": {
                "enabled": True,
                "actor_id": "test/actor",
                "default_input": {"max_results": 10},
            },
            "justjoin": {
                "enabled": False,
                "search_actor_id": "test/search",
                "details_actor_id": "test/details",
                "default_input": {"max_results": 10},
            },
            "nofluffjobs": {
                "enabled": False,
                "actor_id": "test/nfj",
                "default_input": {"max_results": 10},
            },
        }
    }


class TestLoadScoringConfig:
    def test_loads_valid_yaml(self, tmp_path: Path):
        path = _write_yaml(tmp_path / "scoring.yaml", _minimal_scoring_yaml())
        config = load_scoring_config(path)
        assert config.default_cv == "test_cv"
        assert len(config.cvs) == 1
        assert config.weights.keyword == 0.35

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(ConfigFileNotFoundError):
            load_scoring_config(tmp_path / "nonexistent.yaml")

    def test_invalid_weights_raises(self, tmp_path: Path):
        data = _minimal_scoring_yaml()
        data["scoring"]["weights"] = {"keyword": 0.5, "semantic": 0.8}
        path = _write_yaml(tmp_path / "scoring.yaml", data)
        with pytest.raises(InvalidConfigError, match="weights"):
            load_scoring_config(path)


class TestLoadPlatformsConfig:
    def test_loads_valid_yaml(self, tmp_path: Path):
        path = _write_yaml(tmp_path / "platforms.yaml", _minimal_platforms_yaml())
        config = load_platforms_config(path)
        assert config.linkedin.enabled is True
        assert config.justjoin.enabled is False

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(ConfigFileNotFoundError):
            load_platforms_config(tmp_path / "nonexistent.yaml")


class TestScoringWeights:
    def test_valid_weights(self):
        w = ScoringWeights(keyword=0.4, semantic=0.6)
        assert w.keyword == 0.4

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError, match=r"sum to 1\.0"):
            ScoringWeights(keyword=0.3, semantic=0.3)

    def test_weights_tolerance(self):
        w = ScoringWeights(keyword=0.3500001, semantic=0.6500001)
        assert w.keyword == pytest.approx(0.35, abs=0.001)


class TestRealConfigFiles:
    def test_real_scoring_yaml_loads(self):
        from job_matcher.constants import CONFIG_DIR

        config = load_scoring_config(CONFIG_DIR / "scoring.yaml")
        assert len(config.cvs) == 7
        assert config.default_cv == "senior_sdet"
        assert config.weights.keyword + config.weights.semantic == pytest.approx(1.0)

    def test_real_platforms_yaml_loads(self):
        from job_matcher.constants import CONFIG_DIR

        config = load_platforms_config(CONFIG_DIR / "platforms.yaml")
        assert config.linkedin.enabled is True
        assert config.linkedin.actor_id is not None
