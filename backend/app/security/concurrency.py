"""Global concurrency cap for expensive endpoints.

slowapi rate-limits *per IP*, which keeps any single client honest but
doesn't bound the total number of `pefile`/SHAP runs in flight across
the worker. Under a coordinated burst from many IPs the per-IP limit
admits everyone and the host's CPU/memory pays the price.

This module adds the missing layer: a fail-fast counter that admits
up to `limit` simultaneous requests on a registered route and 503s
the next one with a `Retry-After` hint. Inspired by the connection-cap
pattern reverse proxies use, but kept inside the application so the
contract holds even on self-hosted deployments without Cloudflare.

Why fail-fast (return 503) rather than queue:

  - Queueing adds latency that's invisible to the client until it
    times out; 503 with `Retry-After` lets the client back off.
  - Queue depth is itself unbounded unless we cap it, and capping
    the queue is just a slower 503.
  - The dashboard's UX never wants the user staring at a spinner
    longer than the request itself would have taken — better to say
    "busy, retry" than to show a long pause.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import HTTPException, status

from app.config import get_settings


class ConcurrencyGate:
    """Counter-based fail-fast gate.

    `acquire()` raises HTTPException 503 immediately if `inflight >= limit`.
    `release()` decrements the counter, never raising. Both operations are
    serialized through an `asyncio.Lock` so the check-and-increment is
    atomic — without the lock, two concurrent acquires can both see
    `inflight = limit - 1` and increment past the cap.
    """

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError(f"limit must be >= 1, got {limit}")
        self.limit = limit
        self._lock = asyncio.Lock()
        self._inflight = 0

    @property
    def inflight(self) -> int:
        return self._inflight

    async def acquire(self) -> None:
        async with self._lock:
            if self._inflight >= self.limit:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        f"Server busy ({self._inflight}/{self.limit} concurrent "
                        "scans in flight). Retry shortly."
                    ),
                    headers={"Retry-After": "5"},
                )
            self._inflight += 1

    async def release(self) -> None:
        async with self._lock:
            if self._inflight > 0:
                self._inflight -= 1


# Module-level singleton sized from settings at import time. The limit
# is intentionally not hot-reloadable; if you want to retune, restart.
_scan_gate = ConcurrencyGate(get_settings().scan_concurrency_limit)


def get_scan_gate() -> ConcurrencyGate:
    """Exposed for tests to inspect inflight count and reset state."""
    return _scan_gate


async def scan_concurrency_gate() -> AsyncIterator[None]:
    """FastAPI dependency. Yields once a slot is acquired, releases on exit.

    Used via `Depends(scan_concurrency_gate)`. Generator-style means the
    cleanup runs even when the route raises — same semantics as a
    `try/finally`, just expressed at the framework boundary.
    """
    await _scan_gate.acquire()
    try:
        yield
    finally:
        await _scan_gate.release()
