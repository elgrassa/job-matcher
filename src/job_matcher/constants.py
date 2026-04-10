"""Paths, schema versions, magic numbers. No logic."""

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).parents[2]
DATA_DIR: Path = PROJECT_ROOT / "data"
CVS_DIR: Path = PROJECT_ROOT / "cvs"
CONFIG_DIR: Path = PROJECT_ROOT / "config"
LOCK_DIR: Path = DATA_DIR / ".locks"

CURRENT_SCHEMA_VERSION: int = 1

JOBS_FILE: Path = DATA_DIR / "jobs.json"
JOB_SOURCES_FILE: Path = DATA_DIR / "job_sources.json"
CV_VERSIONS_FILE: Path = DATA_DIR / "cv_versions.json"
JD_KEYWORDS_FILE: Path = DATA_DIR / "jd_keywords.json"
MATCH_SCORES_FILE: Path = DATA_DIR / "match_scores.json"
APPLICATIONS_FILE: Path = DATA_DIR / "applications.json"
COST_LEDGER_FILE: Path = DATA_DIR / "cost_ledger.json"

MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
}

DEFAULT_MODEL: str = "claude-haiku-4-5-20251001"
FILELOCK_TIMEOUT_SECONDS: float = 30.0
MAX_LLM_CONCURRENCY: int = 5
COST_WARNING_THRESHOLD_USD: float = 5.00
