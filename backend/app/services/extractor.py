"""Pluggable PE feature extractor.

Two implementations behind one interface:

  - **InProcessExtractor**: calls `extract_features` directly. Default for
    unit tests and dev — fastest, no IPC overhead, but a malformed PE that
    finds a bug in `pefile` would crash the API worker.
  - **SubprocessExtractor**: spawns `python -m app.extractor_worker` per
    request, pipes the bytes over stdin, reads JSON over stdout, and
    enforces a wall-clock timeout. On Unix it also applies
    `setrlimit(RLIMIT_AS)` and `RLIMIT_CPU` to the child via `preexec_fn`.
    A pefile crash blows up the worker, not the API.

The full SECURITY.md posture (separate container, --network=none,
--read-only, dropped caps) is achieved at deploy time by docker-compose
running this same worker inside a hardened sidecar — see
`backend/Dockerfile.extractor`. The subprocess path is OS-level isolation
*plus* the worker stays a single binary you can move between hosts.
"""

from __future__ import annotations

import json
import logging
import subprocess  # noqa: S404 — invoking the worker is the whole point of this module
import sys
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.config import get_settings
from app.services.pe_features import (
    PEFeatures,
    PEParseError,
    SectionFeatures,
    extract_features,
)

log = logging.getLogger(__name__)


@runtime_checkable
class Extractor(Protocol):
    def extract(self, data: bytes) -> PEFeatures: ...


# --- In-process ------------------------------------------------------------


@dataclass(frozen=True)
class InProcessExtractor:
    """Default: parses in the API process. Cheapest, no isolation."""

    def extract(self, data: bytes) -> PEFeatures:
        return extract_features(data)


# --- Subprocess ------------------------------------------------------------


class ExtractorTimeout(PEParseError):
    """Surfaces as a 400 to clients — timing out a parser feels like bad input."""


@dataclass(frozen=True)
class SubprocessExtractor:
    """Forks the worker per request; OS-level isolation today.

    `timeout_seconds` is the wall-clock cap; the SIGKILL on timeout
    matches what a hardened container's runtime limit would do, so
    behavior is the same locally and in production.

    `memory_limit_mb` only takes effect on Unix-like platforms — `RLIMIT_AS`
    doesn't exist on Windows. On Windows the dev workflow falls back to
    timeout-only isolation; the deploy target is Linux, where the full
    set of limits is enforced.
    """

    timeout_seconds: int = 30
    memory_limit_mb: int = 512
    cpu_limit_seconds: int = 30

    def extract(self, data: bytes) -> PEFeatures:
        cmd = [sys.executable, "-m", "app.extractor_worker"]
        kwargs: dict[str, Any] = {
            "input": data,
            "capture_output": True,
            "timeout": self.timeout_seconds,
            "check": False,
        }

        # Resource limits: best-effort on Unix, skipped on Windows.
        if sys.platform != "win32":  # pragma: no cover — exercised on Linux CI
            kwargs["preexec_fn"] = self._make_preexec()

        try:
            proc = subprocess.run(cmd, **kwargs)  # noqa: S603 — argv is hard-coded above
        except subprocess.TimeoutExpired as exc:
            raise ExtractorTimeout(
                f"extractor exceeded {self.timeout_seconds}s wall clock"
            ) from exc

        return _parse_worker_output(proc.returncode, proc.stdout, proc.stderr)

    def _make_preexec(self):  # type: ignore[no-untyped-def]
        # Local import: `resource` is Unix-only.
        import resource

        mem_bytes = self.memory_limit_mb * 1024 * 1024
        cpu = self.cpu_limit_seconds

        def _set_limits() -> None:  # pragma: no cover — Unix-only
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
            # No core dumps — we never want to write the upload to disk.
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        return _set_limits


def _parse_worker_output(returncode: int, stdout: bytes, stderr: bytes) -> PEFeatures:
    """Decode the worker's JSON envelope and rebuild PEFeatures.

    Exit codes:
      0 → ok, features in `features`
      2 → parse failure, error in `error`
      3 → system error, error in `error`
    """
    raw = stdout.strip().decode("utf-8", errors="replace") if stdout else ""

    if returncode != 0 and not raw:
        # Worker crashed before emitting JSON — log a sanitized note and
        # raise. stderr may include traceback, log only its length.
        log.warning("extractor_worker_crashed rc=%s stderr_bytes=%d", returncode, len(stderr or b""))
        raise PEParseError(f"extractor worker failed (rc={returncode})")

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PEParseError("extractor produced unparseable output") from exc

    if not envelope.get("ok"):
        msg = str(envelope.get("error", "unknown extractor error"))
        # Normalize to PEParseError so callers don't need to know about the
        # subprocess path — the router treats it as 400 either way.
        raise PEParseError(msg)

    return _features_from_dict(envelope["features"])


def _features_from_dict(d: dict[str, Any]) -> PEFeatures:
    """Rebuild a frozen PEFeatures dataclass from the worker's JSON.

    Mirror of `PEFeatures.to_dict()` — kept as a thin shim so a future
    schema change is a one-file edit.
    """
    sections = [
        SectionFeatures(
            name=str(s["name"]),
            virtual_size=int(s["virtual_size"]),
            raw_size=int(s["raw_size"]),
            entropy=float(s["entropy"]),
            characteristics=int(s["characteristics"]),
        )
        for s in d.get("sections", [])
    ]
    return PEFeatures(
        schema_version=str(d["schema_version"]),
        sha256=str(d["sha256"]),
        size_bytes=int(d["size_bytes"]),
        machine=int(d["machine"]),
        number_of_sections=int(d["number_of_sections"]),
        time_date_stamp=int(d["time_date_stamp"]),
        characteristics=int(d["characteristics"]),
        magic=int(d["magic"]),
        major_linker_version=int(d["major_linker_version"]),
        minor_linker_version=int(d["minor_linker_version"]),
        size_of_code=int(d["size_of_code"]),
        size_of_initialized_data=int(d["size_of_initialized_data"]),
        size_of_uninitialized_data=int(d["size_of_uninitialized_data"]),
        address_of_entry_point=int(d["address_of_entry_point"]),
        image_base=int(d["image_base"]),
        section_alignment=int(d["section_alignment"]),
        file_alignment=int(d["file_alignment"]),
        subsystem=int(d["subsystem"]),
        dll_characteristics=int(d["dll_characteristics"]),
        size_of_image=int(d["size_of_image"]),
        size_of_headers=int(d["size_of_headers"]),
        imported_dll_count=int(d["imported_dll_count"]),
        imported_function_count=int(d["imported_function_count"]),
        has_signature=bool(d["has_signature"]),
        has_resources=bool(d["has_resources"]),
        has_debug=bool(d["has_debug"]),
        has_tls=bool(d["has_tls"]),
        sections=sections,
        imported_dlls=[str(x) for x in d.get("imported_dlls", [])],
    )


# --- Factory --------------------------------------------------------------


_extractor_cache: Extractor | None = None


def get_extractor() -> Extractor:
    """Return the configured extractor.

    Cached for the process lifetime — the strategy is determined at
    config time, not per-request.
    """
    global _extractor_cache
    if _extractor_cache is not None:
        return _extractor_cache

    settings = get_settings()
    strategy = (settings.extractor_strategy or "inprocess").lower()
    if strategy == "subprocess":
        _extractor_cache = SubprocessExtractor(
            timeout_seconds=settings.extractor_timeout_seconds,
            memory_limit_mb=settings.extractor_memory_mb,
            cpu_limit_seconds=settings.extractor_cpu_seconds,
        )
    elif strategy == "inprocess":
        _extractor_cache = InProcessExtractor()
    else:
        raise ValueError(f"unknown extractor_strategy: {strategy!r}")
    return _extractor_cache


def reset_extractor_cache() -> None:
    """Test hook — clears the singleton so config changes take effect."""
    global _extractor_cache
    _extractor_cache = None
