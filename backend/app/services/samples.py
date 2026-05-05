"""Curated synthetic PE samples for the "Try a sample" gallery.

The gallery exists so a visitor without a Windows PE on hand can still
see the dashboard work end-to-end. Per project policy (no binaries in
git, see SECURITY.md and Step 4 lessons) the samples are *built* on
demand from `app.utils.pe_builder`, not stored as files.

Each sample is a (label, description, builder) bundle. The builder is a
nullary function so the bytes are reproducible — same builder, same
bytes, same SHA-256 every time. That determinism is what makes the
sample's permalink (`/scan/{sha256}`) work indefinitely: even after the
LRU prediction cache evicts the entry, we can rebuild it from the id.

Add a sample by appending to `_SAMPLE_DEFS` below. Keep the list short
(≤6) — this is a gallery, not a catalog.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from app.utils.pe_builder import build_minimal_pe


@dataclass(frozen=True)
class SampleDefinition:
    id: str
    label: str
    description: str
    builder: Callable[[], bytes]


@dataclass(frozen=True)
class SampleInfo:
    """Public metadata — no bytes, suitable for `GET /samples`."""

    id: str
    label: str
    description: str
    sha256: str
    size_bytes: int


def _build_minimal_clean() -> bytes:
    """Tiny PE with a low-entropy NOP-sled section, no imports.

    The model's default response should land near the "benign" side of
    the boundary because almost every malware-distinguishing feature
    (high entropy, lots of imports, suspicious DLL characteristics) is
    absent.
    """
    return build_minimal_pe()


def _build_high_entropy() -> bytes:
    """High-entropy section payload — looks packed/encrypted.

    Uses a deterministic PRNG seeded from a constant so the bytes are
    reproducible across runs (and therefore the SHA-256 is stable, which
    is what permalinks rely on).
    """
    import random

    rng = random.Random(0xC0FFEE)
    payload = bytes(rng.randint(0, 255) for _ in range(4096))
    return build_minimal_pe(section_payload=payload)


def _build_large_code() -> bytes:
    """Large code section — mimics a code-heavy desktop app.

    NOP sled keeps entropy low so the model isn't confused with the
    high-entropy variant. The interesting feature shift is `size_of_code`.
    """
    return build_minimal_pe(section_payload=b"\x90" * 65536)


_SAMPLE_DEFS: tuple[SampleDefinition, ...] = (
    SampleDefinition(
        id="minimal-clean",
        label="Minimal clean PE",
        description=(
            "Tiny synthetic PE with a single low-entropy code section and no "
            "imports. Most malware-distinguishing features are absent — the "
            "model should lean benign."
        ),
        builder=_build_minimal_clean,
    ),
    SampleDefinition(
        id="high-entropy",
        label="High-entropy section (packed-like)",
        description=(
            "Section payload is a deterministic random byte stream, pushing "
            "entropy near the theoretical maximum. Real packed/encrypted "
            "binaries look similar, so the model often shifts toward malicious."
        ),
        builder=_build_high_entropy,
    ),
    SampleDefinition(
        id="large-code",
        label="Large code section",
        description=(
            "Same low-entropy NOP-sled as the minimal clean sample, but 1024× "
            "larger. Demonstrates how `size_of_code` alone moves the prediction "
            "without changing entropy or imports."
        ),
        builder=_build_large_code,
    ),
)


# --- Public lookup API --------------------------------------------------

# Cache the (id → bytes) and (sha256 → id) lookups at import time. Builders
# are deterministic, so caching is safe and avoids re-running the random
# generator on every gallery click.
_BYTES_BY_ID: dict[str, bytes] = {}
_DEF_BY_ID: dict[str, SampleDefinition] = {}
_DEF_BY_HASH: dict[str, SampleDefinition] = {}

for entry in _SAMPLE_DEFS:
    body = entry.builder()
    _BYTES_BY_ID[entry.id] = body
    _DEF_BY_ID[entry.id] = entry
    _DEF_BY_HASH[hashlib.sha256(body).hexdigest()] = entry


def list_samples() -> list[SampleInfo]:
    """Public metadata for the gallery — no bytes."""
    out: list[SampleInfo] = []
    for sample_def in _SAMPLE_DEFS:
        body = _BYTES_BY_ID[sample_def.id]
        out.append(
            SampleInfo(
                id=sample_def.id,
                label=sample_def.label,
                description=sample_def.description,
                sha256=hashlib.sha256(body).hexdigest(),
                size_bytes=len(body),
            )
        )
    return out


def get_sample_bytes(sample_id: str) -> bytes:
    """Return the deterministic bytes for `sample_id`. KeyError if unknown."""
    return _BYTES_BY_ID[sample_id]


def get_sample_by_hash(sha256: str) -> SampleDefinition | None:
    """Permalink fallback — used when /scan/{sha256} misses the cache.

    A sample's bytes can always be rebuilt from its definition, so its
    permalink is permanent regardless of cache state.
    """
    return _DEF_BY_HASH.get(sha256.lower())


def has_sample_id(sample_id: str) -> bool:
    return sample_id in _DEF_BY_ID
