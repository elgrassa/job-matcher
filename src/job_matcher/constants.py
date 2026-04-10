"""Paths, schema versions, magic numbers. No logic."""

from pathlib import Path


def _find_project_root() -> Path:
    """Walk up from CWD looking for pyproject.toml as project root marker."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "pyproject.toml").exists() and (parent / "src" / "job_matcher").exists():
            return parent
    return cwd


PROJECT_ROOT: Path = _find_project_root()
DATA_DIR: Path = PROJECT_ROOT / "data"
CVS_DIR: Path = PROJECT_ROOT / "cvs"
CONFIG_DIR: Path = PROJECT_ROOT / "config"
LOCK_DIR: Path = DATA_DIR / ".locks"

CACHE_DIR: Path = DATA_DIR / ".cache"

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
COST_WARNING_THRESHOLD_USD: float = 5.00
