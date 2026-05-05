"""PE feature extraction.

Parses Windows PE files in memory using `pefile` and emits a stable, flat
feature dict suitable for model inference, SHAP attribution, and JSON
serialization to the frontend.

Design rules (see SECURITY.md):
- Operate on `bytes` only. Never write the upload to disk.
- `pefile` has a history of crashes on malformed input. The parser is wrapped
  in a single try/except that converts every parse-time exception into a
  `PEParseError`, so a hostile sample cannot bring down the worker.
- The feature schema is *frozen* at the point a model is trained. Renaming a
  key, changing dtype, or reordering keys silently invalidates a model. Treat
  `FEATURE_SCHEMA_VERSION` as the contract — bump it whenever the shape
  changes, and pin the value in the model manifest.

The feature set below is the minimum viable cut for a v1 dashboard. It will
be widened to match the published paper's full schema once the trained
artifacts are in hand (see TODO.md, Phase 0).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from typing import Any

import pefile

FEATURE_SCHEMA_VERSION = "0.1.0"

# Frozen feature ordering. Models are trained against this exact sequence;
# adding, removing, or reordering a name silently produces wrong predictions.
# Bump FEATURE_SCHEMA_VERSION whenever this list changes, and the manifest's
# `feature_schema_version` field gates loading.
FEATURE_VECTOR_ORDER: tuple[str, ...] = (
    "size_bytes",
    "machine",
    "number_of_sections",
    "time_date_stamp",
    "characteristics",
    "magic",
    "major_linker_version",
    "minor_linker_version",
    "size_of_code",
    "size_of_initialized_data",
    "size_of_uninitialized_data",
    "address_of_entry_point",
    "image_base",
    "section_alignment",
    "file_alignment",
    "subsystem",
    "dll_characteristics",
    "size_of_image",
    "size_of_headers",
    "imported_dll_count",
    "imported_function_count",
    "has_signature",
    "has_resources",
    "has_debug",
    "has_tls",
    # Section-derived aggregates: stable summaries even though section count
    # varies between PEs.
    "max_section_entropy",
    "mean_section_entropy",
    "total_section_raw_size",
)

# Maximum sections / imported entries we summarize per file. PEs with more are
# truncated; the count itself is preserved as a feature so the truncation is
# never silent.
_MAX_SECTIONS = 16
_MAX_IMPORTED_DLLS = 64


class PEParseError(ValueError):
    """Raised when pefile cannot make sense of the input.

    Wrapping every pefile exception in a single type means callers can do a
    simple `except PEParseError` without knowing about pefile's internals,
    and a malformed sample becomes a 400-class error rather than a 500.
    """


@dataclass(frozen=True)
class SectionFeatures:
    name: str
    virtual_size: int
    raw_size: int
    entropy: float
    characteristics: int


@dataclass(frozen=True)
class PEFeatures:
    """Flat, JSON-serializable feature payload for a single PE file."""

    schema_version: str
    sha256: str
    size_bytes: int

    # COFF header
    machine: int
    number_of_sections: int
    time_date_stamp: int
    characteristics: int

    # Optional header
    magic: int  # PE32 (0x10b) vs PE32+ (0x20b)
    major_linker_version: int
    minor_linker_version: int
    size_of_code: int
    size_of_initialized_data: int
    size_of_uninitialized_data: int
    address_of_entry_point: int
    image_base: int
    section_alignment: int
    file_alignment: int
    subsystem: int
    dll_characteristics: int
    size_of_image: int
    size_of_headers: int

    # Aggregates
    imported_dll_count: int
    imported_function_count: int
    has_signature: bool
    has_resources: bool
    has_debug: bool
    has_tls: bool

    sections: list[SectionFeatures] = field(default_factory=list)
    imported_dlls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Dataclass `asdict` recurses into nested dataclasses already, so
        # `sections` is already a list of dicts here.
        return d

    def to_vector(self) -> list[float]:
        """Return a fixed-order numeric vector for model inference.

        Coupled to `FEATURE_VECTOR_ORDER` and `FEATURE_SCHEMA_VERSION`. The
        return type is `list[float]` rather than `np.ndarray` so this stays
        importable without numpy at parse time; the registry handles the
        cast at the model boundary.
        """
        entropies = [s.entropy for s in self.sections]
        max_entropy = max(entropies) if entropies else 0.0
        mean_entropy = (sum(entropies) / len(entropies)) if entropies else 0.0
        total_raw = sum(s.raw_size for s in self.sections)

        agg = {
            "max_section_entropy": max_entropy,
            "mean_section_entropy": mean_entropy,
            "total_section_raw_size": total_raw,
        }

        out: list[float] = []
        for name in FEATURE_VECTOR_ORDER:
            if name in agg:
                value = agg[name]
            else:
                raw = getattr(self, name)
                value = float(raw) if not isinstance(raw, bool) else float(int(raw))
            out.append(float(value))
        return out


def _shannon_entropy(data: bytes) -> float:
    """Shannon entropy in bits/byte. Empty section → 0.0."""
    if not data:
        return 0.0
    counts = [0] * 256
    for byte in data:
        counts[byte] += 1
    length = len(data)
    entropy = 0.0
    for c in counts:
        if c == 0:
            continue
        p = c / length
        entropy -= p * math.log2(p)
    return entropy


def _decode_section_name(raw: bytes) -> str:
    """Section names are 8-byte ASCII, NUL-padded, sometimes with junk."""
    return raw.rstrip(b"\x00").decode("ascii", errors="replace")


def extract_features(data: bytes) -> PEFeatures:
    """Parse `data` as a PE and return the feature set.

    Raises:
        PEParseError: if `data` is not a parseable PE. The original pefile
            exception is chained via `__cause__` for debugging, but is never
            surfaced to callers — the message is sanitized.
    """
    sha256 = hashlib.sha256(data).hexdigest()

    try:
        # `fast_load=True` skips data-directory parsing; we then call the
        # specific parsers we need. This avoids paying for resource-tree
        # walks we don't use, and keeps the blast radius small if one of the
        # data directories is malformed.
        pe = pefile.PE(data=data, fast_load=True)
        try:
            pe.parse_data_directories(
                directories=[
                    pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                    pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_SECURITY"],
                    pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"],
                    pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DEBUG"],
                    pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_TLS"],
                ]
            )
        except Exception:
            # A broken data directory is interesting (often a sign of packing)
            # but should not abort the whole extraction. Aggregate flags below
            # will simply read False for the missing directories.
            pass
    except pefile.PEFormatError as exc:
        raise PEParseError(f"Not a valid PE: {exc}") from exc
    except Exception as exc:  # last-resort safety net — pefile crashes on hostile input
        raise PEParseError("PE parser failed on this input.") from exc

    try:
        sections = _summarize_sections(pe)
        imported_dlls, imported_function_count = _summarize_imports(pe)

        return PEFeatures(
            schema_version=FEATURE_SCHEMA_VERSION,
            sha256=sha256,
            size_bytes=len(data),
            machine=int(pe.FILE_HEADER.Machine),
            number_of_sections=int(pe.FILE_HEADER.NumberOfSections),
            time_date_stamp=int(pe.FILE_HEADER.TimeDateStamp),
            characteristics=int(pe.FILE_HEADER.Characteristics),
            magic=int(pe.OPTIONAL_HEADER.Magic),
            major_linker_version=int(pe.OPTIONAL_HEADER.MajorLinkerVersion),
            minor_linker_version=int(pe.OPTIONAL_HEADER.MinorLinkerVersion),
            size_of_code=int(pe.OPTIONAL_HEADER.SizeOfCode),
            size_of_initialized_data=int(pe.OPTIONAL_HEADER.SizeOfInitializedData),
            size_of_uninitialized_data=int(pe.OPTIONAL_HEADER.SizeOfUninitializedData),
            address_of_entry_point=int(pe.OPTIONAL_HEADER.AddressOfEntryPoint),
            image_base=int(pe.OPTIONAL_HEADER.ImageBase),
            section_alignment=int(pe.OPTIONAL_HEADER.SectionAlignment),
            file_alignment=int(pe.OPTIONAL_HEADER.FileAlignment),
            subsystem=int(pe.OPTIONAL_HEADER.Subsystem),
            dll_characteristics=int(pe.OPTIONAL_HEADER.DllCharacteristics),
            size_of_image=int(pe.OPTIONAL_HEADER.SizeOfImage),
            size_of_headers=int(pe.OPTIONAL_HEADER.SizeOfHeaders),
            imported_dll_count=len(imported_dlls),
            imported_function_count=imported_function_count,
            has_signature=_has_directory(pe, "IMAGE_DIRECTORY_ENTRY_SECURITY"),
            has_resources=_has_directory(pe, "IMAGE_DIRECTORY_ENTRY_RESOURCE"),
            has_debug=_has_directory(pe, "IMAGE_DIRECTORY_ENTRY_DEBUG"),
            has_tls=_has_directory(pe, "IMAGE_DIRECTORY_ENTRY_TLS"),
            sections=sections,
            imported_dlls=imported_dlls,
        )
    finally:
        # `pefile.PE` keeps the source bytes mapped via mmap-like structures.
        # `close()` releases them eagerly so the upload buffer can be GC'd.
        pe.close()


def _summarize_sections(pe: pefile.PE) -> list[SectionFeatures]:
    out: list[SectionFeatures] = []
    for section in (pe.sections or [])[:_MAX_SECTIONS]:
        try:
            raw = section.get_data() or b""
        except Exception:  # corrupt sections shouldn't abort the whole file
            raw = b""
        out.append(
            SectionFeatures(
                name=_decode_section_name(section.Name),
                virtual_size=int(section.Misc_VirtualSize),
                raw_size=int(section.SizeOfRawData),
                entropy=_shannon_entropy(raw),
                characteristics=int(section.Characteristics),
            )
        )
    return out


def _summarize_imports(pe: pefile.PE) -> tuple[list[str], int]:
    """Return (sorted unique DLL names, total imported function count)."""
    dlls: set[str] = set()
    function_count = 0
    entries = getattr(pe, "DIRECTORY_ENTRY_IMPORT", None) or []
    for entry in entries[:_MAX_IMPORTED_DLLS]:
        name = (entry.dll or b"").decode("ascii", errors="replace").lower()
        if name:
            dlls.add(name)
        function_count += len(entry.imports or [])
    return sorted(dlls), function_count


def _has_directory(pe: pefile.PE, key: str) -> bool:
    """True if the named data directory is present and non-empty.

    `pefile` exposes parsed directories as `DIRECTORY_ENTRY_*` attributes
    (note: the DIRECTORY_ENTRY map keys to integer indices, not attribute
    names). We map `IMAGE_DIRECTORY_ENTRY_X` → `DIRECTORY_ENTRY_X`.
    """
    attr = key.replace("IMAGE_", "")
    value = getattr(pe, attr, None)
    if value is None:
        # Fall back to the raw data directory table — entry exists but
        # parsing was skipped or failed.
        idx = pefile.DIRECTORY_ENTRY.get(key)
        if idx is None:
            return False
        try:
            entry = pe.OPTIONAL_HEADER.DATA_DIRECTORY[idx]
        except (AttributeError, IndexError):
            return False
        return bool(entry.Size)
    if isinstance(value, list):
        return len(value) > 0
    return True
