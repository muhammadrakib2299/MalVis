"""Tests for the global concurrency gate."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.security.concurrency import ConcurrencyGate


@pytest.mark.asyncio
async def test_acquire_release_round_trip():
    gate = ConcurrencyGate(limit=2)
    await gate.acquire()
    assert gate.inflight == 1
    await gate.release()
    assert gate.inflight == 0


@pytest.mark.asyncio
async def test_release_after_exception_keeps_count_consistent():
    gate = ConcurrencyGate(limit=2)
    await gate.acquire()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        await gate.release()
    assert gate.inflight == 0


@pytest.mark.asyncio
async def test_acquire_raises_503_when_full():
    gate = ConcurrencyGate(limit=1)
    await gate.acquire()
    with pytest.raises(HTTPException) as excinfo:
        await gate.acquire()
    assert excinfo.value.status_code == 503
    assert excinfo.value.headers is not None
    assert excinfo.value.headers.get("Retry-After") == "5"
    # Counter does NOT increment on a refused acquire.
    assert gate.inflight == 1
    await gate.release()


@pytest.mark.asyncio
async def test_release_at_zero_is_a_noop():
    """Defensive: a stray release shouldn't drive inflight negative."""
    gate = ConcurrencyGate(limit=1)
    await gate.release()
    await gate.release()
    assert gate.inflight == 0


@pytest.mark.asyncio
async def test_concurrent_acquires_respect_limit():
    """5 simultaneous acquires against limit=3 → 3 succeed, 2 raise 503."""
    gate = ConcurrencyGate(limit=3)

    async def try_acquire() -> bool:
        try:
            await gate.acquire()
            return True
        except HTTPException:
            return False

    results = await asyncio.gather(*(try_acquire() for _ in range(5)))
    assert sum(results) == 3
    assert gate.inflight == 3
    # Drain.
    for _ in range(3):
        await gate.release()
    assert gate.inflight == 0


def test_invalid_limit_rejected():
    with pytest.raises(ValueError):
        ConcurrencyGate(limit=0)
    with pytest.raises(ValueError):
        ConcurrencyGate(limit=-1)
