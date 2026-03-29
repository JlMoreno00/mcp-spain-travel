from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TTLCache(Generic[T]):
    def __init__(self, default_ttl_seconds: int = 3600) -> None:
        self._store: dict[str, tuple[T, float]] = {}
        self._default_ttl = default_ttl_seconds

    def get(self, key: str) -> T | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: T, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        self._store[key] = (value, time.monotonic() + ttl)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


class FileTTLCache(TTLCache[Any]):
    def __init__(self, cache_dir: Path, default_ttl_seconds: int = 86400) -> None:
        super().__init__(default_ttl_seconds)
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe_key = key.replace("/", "_").replace(" ", "_")
        return self._cache_dir / f"{safe_key}.json"

    def get(self, key: str) -> Any | None:
        value = super().get(key)
        if value is not None:
            return value

        path = self._path(key)
        if not path.exists():
            return None

        age = time.time() - path.stat().st_mtime
        if age > self._default_ttl:
            logger.debug("File cache expired for key=%s (age=%.0fs)", key, age)
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            super().set(key, data, ttl_seconds=int(self._default_ttl - age))
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read cache file %s: %s", path, exc)
            return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        super().set(key, value, ttl_seconds)
        path = self._path(key)
        try:
            path.write_text(json.dumps(value, default=str), encoding="utf-8")
        except (TypeError, OSError) as exc:
            logger.warning("Failed to write cache file %s: %s", path, exc)

    def invalidate(self, key: str) -> None:
        super().invalidate(key)
        path = self._path(key)
        if path.exists():
            path.unlink(missing_ok=True)
