"""Ephemeral rank index — maps rank position (1, 2, 3...) to (job_id, cv_id).

Persisted per-profile so `show 1` works across CLI invocations.
"""

import json
import logging

from job_matcher.profile import profile_data_dir

logger = logging.getLogger(__name__)

_INDEX_FILE = "rank_index.json"


def save_rank_index(entries: list[tuple[str, str]]) -> None:
    """Save [(job_id, cv_id), ...] to profile data dir."""
    path = profile_data_dir() / _INDEX_FILE
    data = [{"job_id": jid, "cv_id": cid} for jid, cid in entries]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_rank_index() -> list[tuple[str, str]]:
    path = profile_data_dir() / _INDEX_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [(e["job_id"], e["cv_id"]) for e in data]
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("Corrupt rank index at %s, ignoring", path)
        return []


def resolve_ref(ref: str) -> tuple[str, str] | None:
    """If ref is a digit (rank position), resolve to (job_id, cv_id). Otherwise None."""
    if not ref.isdigit():
        return None
    idx = int(ref) - 1
    entries = _load_rank_index()
    if 0 <= idx < len(entries):
        return entries[idx]
    return None
