"""SHA-256 → ScanResponse cache.

Two reasons this earns its keep:

  1. **Demo speed.** Repeat scans of the same sample (the "Try a sample"
     gallery, an analyst re-checking the same hash) skip pefile parsing,
     feature extraction, and every model in the registry. Latency drops
     from ~tens of milliseconds to a dict lookup.
  2. **Security posture.** The bytes have already been validated and
     parsed once; serving the cached prediction means we don't hand the
     parser the same hostile sample again on retry. SECURITY.md notes
     that we never persist binaries — the cache holds *only* the
     prediction, never the upload bytes.

Bounded LRU + TTL: bounded so a unique-hash flood can't OOM the worker,
TTL so a stale prediction can't hide a model upgrade for longer than the
window. Thread-safe for the uvicorn workers' threadpool.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    """LRU cache with per-entry TTL.

    `OrderedDict` keeps insertion order, so popping the oldest item is
    `O(1)`. Lookups also bump the entry to "most recently used" so an
    actively-hit hash isn't evicted by less popular newcomers.

    Time source is injectable (`time_func`) so tests can advance the
    clock without `time.sleep`.
    """

    def __init__(
        self,
        *,
        max_entries: int,
        ttl_seconds: float,
        time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._max = max_entries
        self._ttl = float(ttl_seconds)
        self._now = time_func
        self._lock = threading.Lock()
        # value → (expires_at, payload)
        self._data: OrderedDict[str, tuple[float, T]] = OrderedDict()

    def get(self, key: str) -> T | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            expires_at, payload = entry
            if expires_at < self._now():
                # Expired — drop and treat as a miss.
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return payload

    def set(self, key: str, value: T) -> None:
        expires_at = self._now() + self._ttl
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (expires_at, value)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
