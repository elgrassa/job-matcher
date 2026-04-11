"""Tests for encrypted local cache."""

import os
import time

import pytest
from cryptography.fernet import Fernet

from job_matcher.cache import LocalCache


class TestEncryptDecryptRoundtrip:
    def test_store_and_load(self, tmp_path):
        key = Fernet.generate_key()
        cache = LocalCache(cache_dir=tmp_path, key=key)
        data = [{"id": "abc", "title": "SDET"}, {"id": "def", "title": "QA"}]
        cache.store("linkedin", data)
        loaded = cache.load("linkedin")
        assert loaded == data

    def test_file_is_encrypted_not_plaintext(self, tmp_path):
        key = Fernet.generate_key()
        cache = LocalCache(cache_dir=tmp_path, key=key)
        cache.store("test", [{"secret": "visible"}])
        enc_path = tmp_path / "test.enc"
        raw = enc_path.read_bytes()
        assert b"visible" not in raw

    def test_wrong_key_returns_none(self, tmp_path):
        key1 = Fernet.generate_key()
        key2 = Fernet.generate_key()
        cache1 = LocalCache(cache_dir=tmp_path, key=key1)
        cache1.store("ns", [{"a": 1}])
        cache2 = LocalCache(cache_dir=tmp_path, key=key2)
        assert cache2.load("ns") is None


class TestTTL:
    def test_expired_cache_returns_none(self, tmp_path):
        key = Fernet.generate_key()
        cache = LocalCache(cache_dir=tmp_path, key=key)
        cache.store("old", [{"x": 1}])
        # Backdate the file
        old_time = time.time() - 25 * 3600
        os.utime(tmp_path / "old.enc", (old_time, old_time))
        assert cache.load("old", max_age_hours=24) is None

    def test_fresh_cache_returns_data(self, tmp_path):
        key = Fernet.generate_key()
        cache = LocalCache(cache_dir=tmp_path, key=key)
        cache.store("fresh", [{"x": 1}])
        assert cache.load("fresh", max_age_hours=24) == [{"x": 1}]


class TestDiff:
    def test_returns_only_new_items(self, tmp_path):
        key = Fernet.generate_key()
        cache = LocalCache(cache_dir=tmp_path, key=key)
        old = [{"id": "a", "title": "Job A"}, {"id": "b", "title": "Job B"}]
        cache.store("jobs", old)
        new = [
            {"id": "b", "title": "Job B"},
            {"id": "c", "title": "Job C"},
        ]
        result = cache.diff("jobs", new, key_field="id")
        assert len(result) == 1
        assert result[0]["id"] == "c"

    def test_no_cache_returns_all(self, tmp_path):
        key = Fernet.generate_key()
        cache = LocalCache(cache_dir=tmp_path, key=key)
        data = [{"id": "x"}]
        result = cache.diff("empty", data, key_field="id")
        assert result == data


class TestClear:
    def test_clear_removes_file(self, tmp_path):
        key = Fernet.generate_key()
        cache = LocalCache(cache_dir=tmp_path, key=key)
        cache.store("rm_me", [{"a": 1}])
        assert (tmp_path / "rm_me.enc").exists()
        cache.clear("rm_me")
        assert not (tmp_path / "rm_me.enc").exists()


class TestFilePermissions:
    def test_cache_file_is_owner_only(self, tmp_path):
        key = Fernet.generate_key()
        cache = LocalCache(cache_dir=tmp_path, key=key)
        cache.store("perm", [{"a": 1}])
        mode = oct(os.stat(tmp_path / "perm.enc").st_mode & 0o777)
        assert mode == "0o600"

    def test_cache_dir_is_owner_only(self, tmp_path):
        cache_dir = tmp_path / "subcache"
        key = Fernet.generate_key()
        LocalCache(cache_dir=cache_dir, key=key)
        mode = oct(os.stat(cache_dir).st_mode & 0o777)
        assert mode == "0o700"


class TestNamespaceValidation:
    def test_valid_namespace(self, tmp_path):
        key = Fernet.generate_key()
        cache = LocalCache(cache_dir=tmp_path, key=key)
        cache.store("linkedin", [{"a": 1}])
        assert cache.load("linkedin") == [{"a": 1}]

    def test_rejects_path_traversal(self, tmp_path):
        key = Fernet.generate_key()
        cache = LocalCache(cache_dir=tmp_path, key=key)
        with pytest.raises(ValueError, match="Invalid cache namespace"):
            cache.store("../../etc/passwd", [])

    def test_rejects_slashes(self, tmp_path):
        key = Fernet.generate_key()
        cache = LocalCache(cache_dir=tmp_path, key=key)
        with pytest.raises(ValueError, match="Invalid cache namespace"):
            cache.store("foo/bar", [])

    def test_allows_hyphens_and_underscores(self, tmp_path):
        key = Fernet.generate_key()
        cache = LocalCache(cache_dir=tmp_path, key=key)
        cache.store("linkedin-2026_04", [{"x": 1}])
        assert cache.load("linkedin-2026_04") == [{"x": 1}]

    def test_rejects_uppercase(self, tmp_path):
        key = Fernet.generate_key()
        cache = LocalCache(cache_dir=tmp_path, key=key)
        with pytest.raises(ValueError, match="Invalid cache namespace"):
            cache.store("LinkedIn", [])


class TestEdgeCases:
    def test_empty_list_roundtrip(self, tmp_path):
        key = Fernet.generate_key()
        cache = LocalCache(cache_dir=tmp_path, key=key)
        cache.store("empty", [])
        assert cache.load("empty") == []

    def test_corrupt_file_returns_none(self, tmp_path):
        key = Fernet.generate_key()
        cache = LocalCache(cache_dir=tmp_path, key=key)
        # Write garbage to the cache file
        (tmp_path / "corrupt.enc").write_bytes(b"not encrypted data")
        assert cache.load("corrupt") is None
