"""User profile management and data migration.

Supports multiple profiles (e.g. husband/wife) sharing scraped jobs
but with separate CVs, scores, applications, and cost tracking.
"""

import logging
import shutil
from pathlib import Path

from job_matcher.constants import DATA_DIR, PROFILES_DIR

logger = logging.getLogger(__name__)

_current_profile: str = "default"


def set_profile(name: str) -> None:
    global _current_profile
    _current_profile = name


def get_profile() -> str:
    return _current_profile


def profile_data_dir(profile: str | None = None) -> Path:
    """Return the data directory for a profile, creating it if needed."""
    p = profile or _current_profile
    d = PROFILES_DIR / p
    d.mkdir(parents=True, exist_ok=True)
    (d / ".locks").mkdir(exist_ok=True)
    return d


def shared_data_dir() -> Path:
    return DATA_DIR


# Files that are per-profile (moved from flat data/ into data/profiles/default/)
_PROFILE_FILES = [
    "cv_versions.json",
    "match_scores.json",
    "applications.json",
    "cost_ledger.json",
]


def migrate_flat_to_profiles() -> bool:
    """Move pre-profile data files into data/profiles/default/. Idempotent."""
    default_dir = PROFILES_DIR / "default"
    if default_dir.exists():
        return False

    default_dir.mkdir(parents=True, exist_ok=True)
    (default_dir / ".locks").mkdir(exist_ok=True)

    moved = 0
    for name in _PROFILE_FILES:
        old_path = DATA_DIR / name
        if old_path.exists():
            shutil.move(str(old_path), str(default_dir / name))
            moved += 1
            logger.info("Migrated %s -> profiles/default/%s", name, name)

    if moved:
        logger.info("Data migration complete: %d files moved to profiles/default/", moved)
    return moved > 0
