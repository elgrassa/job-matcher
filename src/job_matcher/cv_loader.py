"""CV file loading and hash computation."""

import hashlib
import logging
from pathlib import Path

from pydantic import BaseModel

from job_matcher.config import CvRegistryEntry, ScoringConfig
from job_matcher.constants import PROJECT_ROOT
from job_matcher.models import CvVersion
from job_matcher.storage import cvs_store

logger = logging.getLogger(__name__)


class CvLoadError(Exception):
    pass


class CvFileMissingError(CvLoadError):
    pass


class CvRegistryMismatchError(CvLoadError):
    pass


class SyncResult(BaseModel):
    loaded: int
    unchanged: int
    updated: int
    disabled: int


def compute_content_hash(content: str) -> str:
    """Returns 'sha256:' + 64-char hex digest."""
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _read_file_text(path: Path) -> str:
    if not path.exists():
        raise CvFileMissingError(f"CV file not found: {path}")
    return path.read_text(encoding="utf-8")


def load_cv_file(entry: CvRegistryEntry) -> CvVersion:
    """Read file, compute hash, return CvVersion instance."""
    from datetime import UTC, datetime

    file_path = (PROJECT_ROOT / entry.file).resolve()
    if not file_path.is_relative_to(PROJECT_ROOT.resolve()):
        raise CvLoadError(
            f"CV file path escapes project root: {entry.file}"
        )
    content = _read_file_text(file_path)
    content_hash = compute_content_hash(content)
    return CvVersion(
        id=entry.id,
        name=entry.name,
        file_path=entry.file,
        content_hash=content_hash,
        content=content,
        char_count=len(content),
        loaded_at=datetime.now(UTC),
        enabled=entry.enabled,
    )


def load_all_registered_cvs(config: ScoringConfig) -> list[CvVersion]:
    """Load all enabled CVs from scoring config. Disabled entries are skipped with a warning."""
    # Check for duplicate IDs
    ids = [cv.id for cv in config.cvs]
    if len(ids) != len(set(ids)):
        dupes = [i for i in ids if ids.count(i) > 1]
        raise CvRegistryMismatchError(f"Duplicate CV IDs in config: {set(dupes)}")

    results: list[CvVersion] = []
    for entry in config.cvs:
        if not entry.enabled:
            logger.info("Skipping disabled CV: %s", entry.id)
            continue
        try:
            results.append(load_cv_file(entry))
        except CvFileMissingError:
            raise
    return results


def sync_cvs_to_store(config: ScoringConfig) -> SyncResult:
    """Load CVs from disk, upsert into cvs_store, return counts."""
    loaded_cvs = load_all_registered_cvs(config)
    existing = {cv.id: cv for cv in cvs_store.all()}
    config_ids = {entry.id for entry in config.cvs if entry.enabled}

    loaded = 0
    unchanged = 0
    updated = 0
    disabled = 0

    for cv in loaded_cvs:
        old = existing.get(cv.id)
        if old and old.content_hash == cv.content_hash:
            unchanged += 1
            continue
        cvs_store.upsert(cv, lambda c: c.id)
        if old:
            updated += 1
        else:
            loaded += 1

    # Disable CVs in store that are no longer in config
    for cv_id, existing_cv in existing.items():
        if cv_id not in config_ids and existing_cv.enabled:
            existing_cv.enabled = False
            cvs_store.upsert(existing_cv, lambda c: c.id)
            disabled += 1

    return SyncResult(
        loaded=loaded,
        unchanged=unchanged,
        updated=updated,
        disabled=disabled,
    )
