"""Encrypted local cache for scraped data.

Stores raw Apify results encrypted at rest using Fernet (AES-128-CBC).
Key is auto-generated on first use and stored in data/.cache_key (mode 0600).
"""

import json
import logging
import os
import re
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from job_matcher.constants import CACHE_DIR

logger = logging.getLogger(__name__)

_KEY_FILE = CACHE_DIR.parent / ".cache_key"
_NS_PATTERN = re.compile(r"^[a-z0-9_-]+$")


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CACHE_DIR, 0o700)


def _write_secure(path: Path, data: bytes) -> None:
    """Write data to a file with 0o600 permissions from creation (no race window)."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _load_or_create_key() -> bytes:
    """Load Fernet key from disk, or generate one on first use."""
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes().strip()
    _ensure_cache_dir()
    key = Fernet.generate_key()
    _write_secure(_KEY_FILE, key)
    return key


def _validate_namespace(namespace: str) -> str:
    """Validate namespace is safe for use as a filename component."""
    if not _NS_PATTERN.match(namespace):
        raise ValueError(
            f"Invalid cache namespace '{namespace}': "
            "must match [a-z0-9_-]+"
        )
    return namespace


class LocalCache:
    def __init__(self, cache_dir: Path | None = None, key: bytes | None = None):
        self._cache_dir = cache_dir or CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._cache_dir, 0o700)
        self._fernet = Fernet(key or _load_or_create_key())

    def _path(self, namespace: str) -> Path:
        return self._cache_dir / f"{_validate_namespace(namespace)}.enc"

    def store(self, namespace: str, data: list[dict]) -> None:
        """Encrypt and store data to cache file."""
        payload = json.dumps(data, default=str).encode("utf-8")
        encrypted = self._fernet.encrypt(payload)
        path = self._path(namespace)
        _write_secure(path, encrypted)
        logger.info("Cached %d items to %s", len(data), namespace)

    def load(self, namespace: str, max_age_hours: int = 24) -> list[dict] | None:
        """Load cached data if fresh. Returns None if stale or missing."""
        path = self._path(namespace)
        if not path.exists():
            return None
        age_hours = (time.time() - path.stat().st_mtime) / 3600
        if age_hours > max_age_hours:
            logger.info("Cache expired for %s (%.1fh old)", namespace, age_hours)
            return None
        try:
            encrypted = path.read_bytes()
            payload = self._fernet.decrypt(encrypted)
            return json.loads(payload)
        except (InvalidToken, json.JSONDecodeError):
            logger.warning("Failed to decrypt cache for %s, treating as miss", namespace)
            return None

    def diff(
        self, namespace: str, new_data: list[dict], key_field: str
    ) -> list[dict]:
        """Return items from new_data that are not in the cached version."""
        cached = self.load(namespace)
        if cached is None:
            return new_data
        cached_keys = {item.get(key_field) for item in cached if item.get(key_field)}
        return [item for item in new_data if item.get(key_field) not in cached_keys]

    def clear(self, namespace: str) -> None:
        """Delete a cached namespace."""
        path = self._path(namespace)
        if path.exists():
            path.unlink()
