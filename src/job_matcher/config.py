"""Configuration loading from yaml and env."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from job_matcher.constants import CONFIG_DIR


class ConfigFileNotFoundError(Exception):
    pass


class InvalidConfigError(Exception):
    pass


class ApifySettings(BaseSettings):
    APIFY_TOKEN: str
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class AnthropicSettings(BaseSettings):
    ANTHROPIC_API_KEY: str
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class HardFilterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_daily_rate_eur: float = 320.0
    min_hourly_rate_eur: float = 40.0
    reject_hybrid: bool = True
    eu_citizenship_keywords: list[str]
    us_work_authorization_keywords: list[str] = []
    us_location_keywords: list[str] = []
    onsite_compatible_cities: list[str]


class ScoringWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: float = 0.35
    semantic: float = 0.65

    @model_validator(mode="after")
    def sum_to_one(self) -> "ScoringWeights":
        total = self.keyword + self.semantic
        if not 0.99 <= total <= 1.01:
            raise ValueError(f"weights must sum to 1.0, got {total}")
        return self


class WarningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score_delta_threshold: float = 0.12
    keyword_delta_threshold: float = 0.25


class CvRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    file: str
    description: str
    enabled: bool = True


class ScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_model: str = "claude-haiku-4-5-20251001"
    max_tokens_per_call: int = 500
    concurrent_llm_calls: int = 5
    weights: ScoringWeights
    warning: WarningConfig
    hard_filters: HardFilterConfig
    cvs: list[CvRegistryEntry]
    default_cv: str


class PlatformConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool
    actor_id: str | None = None
    search_actor_id: str | None = None
    details_actor_id: str | None = None
    default_input: dict[str, Any]


class PlatformsConfig(BaseModel):
    linkedin: PlatformConfig
    justjoin: PlatformConfig
    nofluffjobs: PlatformConfig


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigFileNotFoundError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise InvalidConfigError(f"Expected dict in {path}, got {type(data).__name__}")
    return data


def load_scoring_config(path: Path | None = None) -> ScoringConfig:
    p = path or (CONFIG_DIR / "scoring.yaml")
    data = _read_yaml(p)
    try:
        scoring_raw = data.get("scoring", {})
        cvs_raw = data.get("cvs", {})
        return ScoringConfig(
            **scoring_raw,
            cvs=cvs_raw.get("versions", []),
            default_cv=cvs_raw.get("default", ""),
        )
    except Exception as e:
        raise InvalidConfigError(f"Invalid scoring config in {p}: {e}") from e


def load_platforms_config(path: Path | None = None) -> PlatformsConfig:
    p = path or (CONFIG_DIR / "platforms.yaml")
    data = _read_yaml(p)
    try:
        return PlatformsConfig(**data.get("platforms", {}))
    except Exception as e:
        raise InvalidConfigError(f"Invalid platforms config in {p}: {e}") from e


def load_apify_settings() -> ApifySettings:
    return ApifySettings()  # type: ignore[call-arg]


def load_anthropic_settings() -> AnthropicSettings:
    return AnthropicSettings()  # type: ignore[call-arg]
