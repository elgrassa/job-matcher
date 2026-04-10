"""Comprehensive tests for JsonStore."""

import json
import threading
from pathlib import Path

import pytest
from pydantic import BaseModel

from job_matcher.storage import (
    JsonStore,
    LockTimeoutError,
    SchemaVersionMismatchError,
    StorageError,
    _empty_envelope,
)


class SimpleItem(BaseModel):
    id: str
    name: str
    value: int = 0


def _key(item: SimpleItem) -> str:
    return item.id


def _make_store(tmp_path: Path, items: list[SimpleItem] | None = None) -> JsonStore[SimpleItem]:
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir(exist_ok=True)
    store = JsonStore(
        file_path=tmp_path / "test.json",
        model=SimpleItem,
        lock_dir=lock_dir,
    )
    if items:
        store.save_all(items)
    return store


class TestEmptyStore:
    def test_returns_empty_list(self, tmp_path: Path):
        store = _make_store(tmp_path)
        assert store.all() == []

    def test_count_returns_zero(self, tmp_path: Path):
        store = _make_store(tmp_path)
        assert store.count() == 0


class TestSaveAndRead:
    def test_roundtrip(self, tmp_path: Path):
        store = _make_store(tmp_path)
        items = [SimpleItem(id="a", name="Alpha"), SimpleItem(id="b", name="Beta")]
        store.save_all(items)
        loaded = store.all()
        assert len(loaded) == 2
        assert loaded[0].id == "a"
        assert loaded[1].name == "Beta"

    def test_json_is_human_readable(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save_all([SimpleItem(id="x", name="Test")])
        raw = (tmp_path / "test.json").read_text()
        data = json.loads(raw)
        assert data["schema_version"] == 1
        assert isinstance(data["entities"], list)
        assert data["entities"][0]["id"] == "x"

    def test_envelope_has_updated_at(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save_all([SimpleItem(id="x", name="Test")])
        raw = json.loads((tmp_path / "test.json").read_text())
        assert "updated_at" in raw


class TestUpsert:
    def test_inserts_new_item(self, tmp_path: Path):
        store = _make_store(tmp_path)
        result = store.upsert(SimpleItem(id="a", name="Alpha"), _key)
        assert result.inserted is True
        assert result.item_key == "a"
        assert store.count() == 1

    def test_updates_existing_item(self, tmp_path: Path):
        store = _make_store(tmp_path, [SimpleItem(id="a", name="Alpha")])
        result = store.upsert(SimpleItem(id="a", name="Alpha Updated", value=42), _key)
        assert result.inserted is False
        items = store.all()
        assert len(items) == 1
        assert items[0].name == "Alpha Updated"
        assert items[0].value == 42


class TestUpsertMany:
    def test_mixed_insert_update(self, tmp_path: Path):
        store = _make_store(tmp_path, [SimpleItem(id="a", name="A")])
        result = store.upsert_many(
            [
                SimpleItem(id="a", name="A Updated"),
                SimpleItem(id="b", name="B New"),
                SimpleItem(id="c", name="C New"),
            ],
            _key,
        )
        assert result.inserted == 2
        assert result.updated == 1
        assert result.total == 3
        assert store.count() == 3


class TestFind:
    def test_returns_matches(self, tmp_path: Path):
        store = _make_store(
            tmp_path,
            [
                SimpleItem(id="a", name="Alpha", value=10),
                SimpleItem(id="b", name="Beta", value=20),
                SimpleItem(id="c", name="Charlie", value=10),
            ],
        )
        results = store.find(lambda x: x.value == 10)
        assert len(results) == 2
        assert {r.id for r in results} == {"a", "c"}

    def test_find_one_returns_first_match(self, tmp_path: Path):
        store = _make_store(
            tmp_path,
            [SimpleItem(id="a", name="Alpha"), SimpleItem(id="b", name="Beta")],
        )
        result = store.find_one(lambda x: x.name.startswith("B"))
        assert result is not None
        assert result.id == "b"

    def test_find_one_returns_none(self, tmp_path: Path):
        store = _make_store(tmp_path, [SimpleItem(id="a", name="Alpha")])
        assert store.find_one(lambda x: x.id == "z") is None


class TestGetByKey:
    def test_returns_exact_match(self, tmp_path: Path):
        store = _make_store(
            tmp_path,
            [SimpleItem(id="a", name="Alpha"), SimpleItem(id="b", name="Beta")],
        )
        result = store.get_by_key(_key, "b")
        assert result is not None
        assert result.name == "Beta"

    def test_returns_none_for_missing(self, tmp_path: Path):
        store = _make_store(tmp_path, [SimpleItem(id="a", name="Alpha")])
        assert store.get_by_key(_key, "z") is None


class TestDelete:
    def test_removes_matching(self, tmp_path: Path):
        store = _make_store(
            tmp_path,
            [
                SimpleItem(id="a", name="Alpha"),
                SimpleItem(id="b", name="Beta"),
                SimpleItem(id="c", name="Charlie"),
            ],
        )
        deleted = store.delete(lambda x: x.id == "b")
        assert deleted == 1
        assert store.count() == 2
        assert store.get_by_key(_key, "b") is None

    def test_delete_no_match(self, tmp_path: Path):
        store = _make_store(tmp_path, [SimpleItem(id="a", name="Alpha")])
        assert store.delete(lambda x: x.id == "z") == 0
        assert store.count() == 1


class TestSchemaVersion:
    def test_mismatch_raises(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        file_path = tmp_path / "test.json"
        data = _empty_envelope(999)
        data["entities"] = [{"id": "a", "name": "A"}]
        file_path.write_text(json.dumps(data))
        store = JsonStore(file_path=file_path, model=SimpleItem, lock_dir=lock_dir)
        with pytest.raises(SchemaVersionMismatchError, match="999"):
            store.all()

    def test_valid_version_reads_ok(self, tmp_path: Path):
        store = _make_store(tmp_path, [SimpleItem(id="a", name="Alpha")])
        assert store.count() == 1


class TestInvalidJson:
    def test_raises_clear_error(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        file_path = tmp_path / "test.json"
        file_path.write_text("not json at all{{{")
        store = JsonStore(file_path=file_path, model=SimpleItem, lock_dir=lock_dir)
        with pytest.raises(StorageError, match="Invalid JSON"):
            store.all()

    def test_missing_entities_raises(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        file_path = tmp_path / "test.json"
        file_path.write_text(json.dumps({"schema_version": 1, "updated_at": "now"}))
        store = JsonStore(file_path=file_path, model=SimpleItem, lock_dir=lock_dir)
        with pytest.raises(StorageError, match="entities"):
            store.all()


class TestAtomicWrite:
    def test_leaves_no_tmp_file(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save_all([SimpleItem(id="a", name="Alpha")])
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


class TestConcurrentWrites:
    def test_no_data_loss(self, tmp_path: Path):
        store = _make_store(tmp_path)
        errors: list[Exception] = []

        def writer(thread_id: int):
            try:
                for i in range(10):
                    store.upsert(
                        SimpleItem(id=f"t{thread_id}_i{i}", name=f"Thread {thread_id} Item {i}"),
                        _key,
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        items = store.all()
        assert len(items) == 100


class TestLockTimeout:
    def test_raises_on_timeout(self, tmp_path: Path):
        from filelock import FileLock

        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        file_path = tmp_path / "test.json"

        external_lock = FileLock(lock_dir / "test.lock")
        external_lock.acquire()
        try:
            store = JsonStore(
                file_path=file_path, model=SimpleItem, lock_dir=lock_dir, timeout=0.1
            )
            with pytest.raises(LockTimeoutError):
                store.all()
        finally:
            external_lock.release()


class TestEmptyFile:
    def test_empty_file_returns_empty_list(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        file_path = tmp_path / "test.json"
        file_path.write_text("")
        store = JsonStore(file_path=file_path, model=SimpleItem, lock_dir=lock_dir)
        assert store.all() == []


class TestSaveAllOverwrite:
    def test_replaces_all_existing_data(self, tmp_path: Path):
        store = _make_store(
            tmp_path,
            [SimpleItem(id="a", name="A"), SimpleItem(id="b", name="B")],
        )
        assert store.count() == 2
        store.save_all([SimpleItem(id="x", name="X")])
        items = store.all()
        assert len(items) == 1
        assert items[0].id == "x"


class TestDeleteMultiple:
    def test_deletes_all_matching(self, tmp_path: Path):
        store = _make_store(
            tmp_path,
            [
                SimpleItem(id="a", name="group1", value=1),
                SimpleItem(id="b", name="group1", value=1),
                SimpleItem(id="c", name="group2", value=2),
            ],
        )
        deleted = store.delete(lambda x: x.value == 1)
        assert deleted == 2
        assert store.count() == 1
        assert store.all()[0].id == "c"


class TestMigrationBumpsVersion:
    def test_old_version_gets_bumped_on_read(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        file_path = tmp_path / "test.json"
        data = {
            "schema_version": 0,
            "updated_at": "2026-01-01T00:00:00+00:00",
            "entities": [{"id": "a", "name": "A", "value": 0}],
        }
        file_path.write_text(json.dumps(data))
        store = JsonStore(
            file_path=file_path, model=SimpleItem, lock_dir=lock_dir, schema_version=1
        )
        items = store.all()
        assert len(items) == 1
        # After a write, the version should be bumped
        store.save_all(items)
        raw = json.loads(file_path.read_text())
        assert raw["schema_version"] == 1
