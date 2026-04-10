"""All Pydantic models."""

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class RawJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["linkedin", "justjoin", "nofluffjobs"]
    platform_job_id: str | None
    url: str
    title: str
    company: str
    location: str | None
    description: str
    salary_raw: str | None
    employment_type_raw: str | None
    remote_type_raw: str | None
    posted_at_raw: str | None
    raw: dict[str, Any]


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    company: str
    location: str | None
    description: str

    salary_min: float | None
    salary_max: float | None
    salary_currency: Literal["EUR", "USD", "PLN", "CHF", "GBP"] | None
    salary_period: Literal["hour", "day", "month", "year"] | None

    employment_type: Literal["b2b", "permanent", "contract", "internship", "unknown"]
    remote_type: Literal["remote", "hybrid", "onsite", "unknown"]
    seniority: Literal["junior", "mid", "senior", "expert", "lead", "principal", "unknown"]

    posted_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    scraped_at: datetime

    @field_validator("first_seen_at", "last_seen_at", "scraped_at", "posted_at")
    @classmethod
    def require_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if v.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        return v.astimezone(UTC)

    @field_validator("salary_max")
    @classmethod
    def max_ge_min(cls, v: float | None, info: ValidationInfo) -> float | None:
        smin = info.data.get("salary_min")
        if v is not None and smin is not None and v < smin:
            raise ValueError(f"salary_max ({v}) < salary_min ({smin})")
        return v


class JobSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    platform: Literal["linkedin", "justjoin", "nofluffjobs"]
    platform_job_id: str | None
    url: str
    scraped_at: datetime
    raw: dict[str, Any]

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v


class CvVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    file_path: str
    content_hash: str
    content: str
    char_count: int
    loaded_at: datetime
    enabled: bool = True

    @field_validator("content_hash")
    @classmethod
    def hash_format(cls, v: str) -> str:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", v):
            raise ValueError("content_hash must be 'sha256:' + 64 lowercase hex chars")
        return v

    @field_validator("id")
    @classmethod
    def id_slug(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
            raise ValueError("id must be lowercase snake_case")
        return v


class JdKeywords(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    must_have: list[str]
    nice_to_have: list[str]
    extracted_at: datetime
    job_description_hash: str

    @field_validator("must_have", "nice_to_have")
    @classmethod
    def normalize_keywords(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for kw in v:
            k = kw.strip().lower()
            if k and k not in seen:
                seen.add(k)
                out.append(k)
        return out


class MatchScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    cv_id: str

    keyword_score: float
    keywords_required: list[str]
    keywords_matched: list[str]
    keywords_missing: list[str]

    semantic_score: float
    reasoning: str
    green_flags: list[str]
    red_flags: list[str]
    llm_model_used: str

    final_score: float

    hard_filter_triggered: str | None

    scored_at: datetime
    cv_content_hash: str
    jd_keyword_hash: str

    @field_validator("keyword_score", "semantic_score", "final_score")
    @classmethod
    def score_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"score must be in [0.0, 1.0], got {v}")
        return round(v, 4)


class ApplicationStatus(StrEnum):
    SAVED = "saved"
    APPLIED = "applied"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    GHOSTED = "ghosted"


class Application(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    job_id: str
    cv_id: str
    status: ApplicationStatus
    saved_at: datetime | None
    applied_at: datetime | None
    last_status_change_at: datetime
    notes: str = ""
    status_history: list[dict[str, Any]] = Field(default_factory=list)


class CostLedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    timestamp: datetime
    command: str
    operation: Literal["keyword_extraction", "semantic_scoring"]
    job_id: str | None
    cv_id: str | None
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)
