"""Tests for the TTL LRU cache."""

from __future__ import annotations

import threading

import pytest

from app.services.cache import TTLCache


class _Clock:
    """Manually advanced clock for deterministic TTL tests."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_get_returns_set_value():
    cache: TTLCache[str] = TTLCache(max_entries=4, ttl_seconds=10)
    cache.set("a", "alpha")
    assert cache.get("a") == "alpha"


def test_get_returns_none_for_missing_key():
    cache: TTLCache[str] = TTLCache(max_entries=4, ttl_seconds=10)
    assert cache.get("nope") is None


def test_entries_expire_after_ttl():
    clock = _Clock()
    cache: TTLCache[str] = TTLCache(max_entries=4, ttl_seconds=5, time_func=clock)
    cache.set("a", "alpha")
    clock.advance(4.9)
    assert cache.get("a") == "alpha"
    clock.advance(0.2)  # 5.1s elapsed total — past TTL
    assert cache.get("a") is None


def test_lru_eviction_when_over_capacity():
    cache: TTLCache[str] = TTLCache(max_entries=2, ttl_seconds=1000)
    cache.set("a", "1")
    cache.set("b", "2")
    cache.set("c", "3")  # evicts "a"
    assert cache.get("a") is None
    assert cache.get("b") == "2"
    assert cache.get("c") == "3"


def test_get_promotes_to_most_recently_used():
    cache: TTLCache[str] = TTLCache(max_entries=2, ttl_seconds=1000)
    cache.set("a", "1")
    cache.set("b", "2")
    # Touch "a" → "b" becomes the LRU.
    assert cache.get("a") == "1"
    cache.set("c", "3")
    assert cache.get("a") == "1"
    assert cache.get("b") is None
    assert cache.get("c") == "3"


def test_concurrent_writes_do_not_corrupt():
    cache: TTLCache[int] = TTLCache(max_entries=64, ttl_seconds=1000)

    def worker(start: int) -> None:
        for i in range(100):
            cache.set(f"k{(start + i) % 32}", start + i)
            cache.get(f"k{(start + i) % 32}")

    threads = [threading.Thread(target=worker, args=(t * 100,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(cache) <= 64


def test_rejects_invalid_config():
    with pytest.raises(ValueError):
        TTLCache(max_entries=0, ttl_seconds=1)
    with pytest.raises(ValueError):
        TTLCache(max_entries=1, ttl_seconds=0)
