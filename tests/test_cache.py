from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.cache.manager import FileTTLCache, TTLCache


class TestTTLCache:
    def test_set_and_get_returns_value(self):
        cache: TTLCache[str] = TTLCache(default_ttl_seconds=60)
        cache.set("key", "hello")
        assert cache.get("key") == "hello"

    def test_get_missing_key_returns_none(self):
        cache: TTLCache[str] = TTLCache(default_ttl_seconds=60)
        assert cache.get("nonexistent") is None

    def test_value_expires_after_ttl(self):
        cache: TTLCache[str] = TTLCache(default_ttl_seconds=10)
        with patch("src.cache.manager.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            cache.set("key", "value")

            mock_time.monotonic.return_value = 1009.9
            assert cache.get("key") == "value"

            mock_time.monotonic.return_value = 1010.1
            assert cache.get("key") is None

    def test_custom_ttl_per_entry(self):
        cache: TTLCache[int] = TTLCache(default_ttl_seconds=100)
        with patch("src.cache.manager.time") as mock_time:
            mock_time.monotonic.return_value = 500.0
            cache.set("short", 1, ttl_seconds=5)
            cache.set("long", 2, ttl_seconds=60)

            mock_time.monotonic.return_value = 506.0
            assert cache.get("short") is None
            assert cache.get("long") == 2

    def test_invalidate_removes_entry(self):
        cache: TTLCache[str] = TTLCache()
        cache.set("key", "value")
        cache.invalidate("key")
        assert cache.get("key") is None

    def test_invalidate_missing_key_noop(self):
        cache: TTLCache[str] = TTLCache()
        cache.invalidate("never_set")

    def test_clear_removes_all_entries(self):
        cache: TTLCache[str] = TTLCache()
        cache.set("a", "1")
        cache.set("b", "2")
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_overwrite_updates_value(self):
        cache: TTLCache[str] = TTLCache(default_ttl_seconds=60)
        cache.set("key", "old")
        cache.set("key", "new")
        assert cache.get("key") == "new"


class TestFileTTLCache:
    def test_write_and_read_from_memory(self, tmp_path: Path):
        cache = FileTTLCache(cache_dir=tmp_path, default_ttl_seconds=3600)
        with patch("src.cache.manager.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            mock_time.time.return_value = 1000.0
            cache.set("data", [1, 2, 3])

            mock_time.monotonic.return_value = 1001.0
            mock_time.time.return_value = 1001.0
            assert cache.get("data") == [1, 2, 3]

    def test_persists_to_disk(self, tmp_path: Path):
        cache = FileTTLCache(cache_dir=tmp_path, default_ttl_seconds=3600)
        payload = {"stations": ["Madrid", "Barcelona"]}
        with patch("src.cache.manager.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            mock_time.time.return_value = 1000.0
            cache.set("stations", payload)

        json_file = tmp_path / "stations.json"
        assert json_file.exists()
        assert json.loads(json_file.read_text()) == payload

    def test_reads_from_disk_on_cold_start(self, tmp_path: Path):
        payload = {"city": "Madrid"}
        cache_file = tmp_path / "mykey.json"
        cache_file.write_text(json.dumps(payload))

        cache = FileTTLCache(cache_dir=tmp_path, default_ttl_seconds=3600)
        with patch("src.cache.manager.time") as mock_time:
            mock_time.monotonic.return_value = 2000.0
            mock_time.time.return_value = time.time()
            result = cache.get("mykey")

        assert result == payload

    def test_file_expires_when_too_old(self, tmp_path: Path):
        payload = {"old": True}
        cache_file = tmp_path / "stale.json"
        cache_file.write_text(json.dumps(payload))

        cache = FileTTLCache(cache_dir=tmp_path, default_ttl_seconds=3600)
        with patch("src.cache.manager.time") as mock_time:
            mock_time.monotonic.return_value = 5000.0
            mock_time.time.return_value = time.time() + 7200
            result = cache.get("stale")

        assert result is None

    def test_handles_corrupt_json_gracefully(self, tmp_path: Path):
        bad_file = tmp_path / "broken.json"
        bad_file.write_text("{ not valid json !!!")

        cache = FileTTLCache(cache_dir=tmp_path, default_ttl_seconds=3600)
        with patch("src.cache.manager.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            mock_time.time.return_value = time.time()
            assert cache.get("broken") is None

    def test_invalidate_removes_file(self, tmp_path: Path):
        cache = FileTTLCache(cache_dir=tmp_path, default_ttl_seconds=3600)
        with patch("src.cache.manager.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            mock_time.time.return_value = 1000.0
            cache.set("todelete", {"x": 1})

        assert (tmp_path / "todelete.json").exists()
        cache.invalidate("todelete")
        assert not (tmp_path / "todelete.json").exists()
        assert cache.get("todelete") is None

    def test_key_with_slashes_maps_to_safe_filename(self, tmp_path: Path):
        cache = FileTTLCache(cache_dir=tmp_path, default_ttl_seconds=3600)
        with patch("src.cache.manager.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            mock_time.time.return_value = 1000.0
            cache.set("renfe/stations/v1", [1, 2])

        safe_file = tmp_path / "renfe_stations_v1.json"
        assert safe_file.exists()
