"""JSON file-backed storage with filelock."""

import contextlib
import json
import os
import tempfile
from collections.abc import Callable, Hashable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generic, TypeVar

from filelock import FileLock, Timeout
from pydantic import BaseModel

from job_matcher.constants import (
    APPLICATIONS_FILE,
    COST_LEDGER_FILE,
    CURRENT_SCHEMA_VERSION,
    CV_VERSIONS_FILE,
    FILELOCK_TIMEOUT_SECONDS,
    JD_KEYWORDS_FILE,
    JOB_SOURCES_FILE,
    JOBS_FILE,
    LOCK_DIR,
    MATCH_SCORES_FILE,
)

T = TypeVar("T", bound=BaseModel)


class StorageError(Exception):
    pass


class SchemaVersionMismatchError(StorageError):
    pass


class LockTimeoutError(StorageError):
    pass


class UpsertResult(BaseModel):
    inserted: bool
    item_key: str


class UpsertBatchResult(BaseModel):
    inserted: int
    updated: int
    skipped: int
    total: int


def _empty_envelope(schema_version: int) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "updated_at": datetime.now(UTC).isoformat(),
        "entities": [],
    }


def _atomic_write(path: Path, content: str) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


class JsonStore(Generic[T]):
    def __init__(
        self,
        file_path: Path,
        model: type[T],
        lock_dir: Path = LOCK_DIR,
        schema_version: int = CURRENT_SCHEMA_VERSION,
    ):
        self._file_path = file_path
        self._model = model
        self._schema_version = schema_version
        self._lock_path = lock_dir / f"{file_path.stem}.lock"
        lock_dir.mkdir(parents=True, exist_ok=True)

    def _acquire_lock(self) -> FileLock:
        lock = FileLock(self._lock_path, timeout=FILELOCK_TIMEOUT_SECONDS)
        try:
            lock.acquire()
        except Timeout as e:
            raise LockTimeoutError(
                f"Could not acquire lock for {self._file_path} within "
                f"{FILELOCK_TIMEOUT_SECONDS}s. Delete {self._lock_path} if stale."
            ) from e
        return lock

    def _read_raw(self) -> dict[str, Any]:
        if not self._file_path.exists():
            return _empty_envelope(self._schema_version)
        text = self._file_path.read_text(encoding="utf-8")
        if not text.strip():
            return _empty_envelope(self._schema_version)
        try:
            data: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError as e:
            raise StorageError(f"Invalid JSON in {self._file_path}: {e}") from e
        self._validate_envelope(data)
        return data

    def _validate_envelope(self, data: dict[str, Any]) -> None:
        file_version = data.get("schema_version")
        if file_version is None:
            raise StorageError(f"Missing schema_version in {self._file_path}")
        if file_version > self._schema_version:
            raise SchemaVersionMismatchError(
                f"{self._file_path} has schema_version {file_version}, "
                f"but this tool supports up to {self._schema_version}. "
                "Upgrade the tool or migrate the data."
            )
        if file_version < self._schema_version:
            data.update(self._migrate(data, file_version))
        if not isinstance(data.get("entities"), list):
            raise StorageError(f"'entities' must be a list in {self._file_path}")

    def _migrate(self, data: dict[str, Any], from_version: int) -> dict[str, Any]:
        # No migrations yet (we're on v1). Future: chain _migrate_v1_to_v2, etc.
        _ = from_version
        return data

    def _write_raw(self, data: dict[str, Any]) -> None:
        data["updated_at"] = datetime.now(UTC).isoformat()
        content = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        _atomic_write(self._file_path, content)

    def _deserialize(self, raw_entities: list[dict[str, Any]]) -> list[T]:
        items: list[T] = []
        for raw in raw_entities:
            items.append(self._model.model_validate(raw))
        return items

    def _serialize(self, items: list[T]) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in items]

    def all(self) -> list[T]:
        lock = self._acquire_lock()
        try:
            data = self._read_raw()
        finally:
            lock.release()
        return self._deserialize(data["entities"])

    def find(self, predicate: Callable[[T], bool]) -> list[T]:
        return [item for item in self.all() if predicate(item)]

    def find_one(self, predicate: Callable[[T], bool]) -> T | None:
        for item in self.all():
            if predicate(item):
                return item
        return None

    def get_by_key(self, key_fn: Callable[[T], Hashable], key_value: Hashable) -> T | None:
        for item in self.all():
            if key_fn(item) == key_value:
                return item
        return None

    def save_all(self, items: list[T]) -> None:
        lock = self._acquire_lock()
        try:
            data = _empty_envelope(self._schema_version)
            data["entities"] = self._serialize(items)
            self._write_raw(data)
        finally:
            lock.release()

    def upsert(self, item: T, key_fn: Callable[[T], Hashable]) -> UpsertResult:
        lock = self._acquire_lock()
        try:
            data = self._read_raw()
            entities = self._deserialize(data["entities"])
            item_key = key_fn(item)
            key_map = {key_fn(e): i for i, e in enumerate(entities)}
            inserted = item_key not in key_map
            if inserted:
                entities.append(item)
            else:
                entities[key_map[item_key]] = item
            data["entities"] = self._serialize(entities)
            self._write_raw(data)
        finally:
            lock.release()
        return UpsertResult(inserted=inserted, item_key=str(item_key))

    def upsert_many(
        self, items: list[T], key_fn: Callable[[T], Hashable]
    ) -> UpsertBatchResult:
        lock = self._acquire_lock()
        try:
            data = self._read_raw()
            entities = self._deserialize(data["entities"])
            key_map = {key_fn(e): i for i, e in enumerate(entities)}
            inserted = 0
            updated = 0
            for item in items:
                item_key = key_fn(item)
                if item_key in key_map:
                    entities[key_map[item_key]] = item
                    updated += 1
                else:
                    key_map[item_key] = len(entities)
                    entities.append(item)
                    inserted += 1
            data["entities"] = self._serialize(entities)
            self._write_raw(data)
        finally:
            lock.release()
        return UpsertBatchResult(
            inserted=inserted,
            updated=updated,
            skipped=len(items) - inserted - updated,
            total=len(items),
        )

    def delete(self, predicate: Callable[[T], bool]) -> int:
        lock = self._acquire_lock()
        try:
            data = self._read_raw()
            entities = self._deserialize(data["entities"])
            before = len(entities)
            entities = [e for e in entities if not predicate(e)]
            data["entities"] = self._serialize(entities)
            self._write_raw(data)
        finally:
            lock.release()
        return before - len(entities)

    def count(self) -> int:
        return len(self.all())


def _make_store(file_path: Path, model: type[T]) -> JsonStore[T]:
    return JsonStore(file_path=file_path, model=model)


# Lazy store creation: import models here to avoid circular imports at module level
def _create_typed_stores() -> (
    tuple[
        JsonStore, JsonStore, JsonStore, JsonStore, JsonStore, JsonStore, JsonStore
    ]
):
    from job_matcher.models import (
        Application,
        CostLedgerEntry,
        CvVersion,
        JdKeywords,
        Job,
        JobSource,
        MatchScore,
    )

    return (
        _make_store(JOBS_FILE, Job),
        _make_store(JOB_SOURCES_FILE, JobSource),
        _make_store(CV_VERSIONS_FILE, CvVersion),
        _make_store(JD_KEYWORDS_FILE, JdKeywords),
        _make_store(MATCH_SCORES_FILE, MatchScore),
        _make_store(APPLICATIONS_FILE, Application),
        _make_store(COST_LEDGER_FILE, CostLedgerEntry),
    )


# Module-level typed store instances
(
    jobs_store,
    sources_store,
    cvs_store,
    keywords_store,
    scores_store,
    applications_store,
    cost_store,
) = _create_typed_stores()
