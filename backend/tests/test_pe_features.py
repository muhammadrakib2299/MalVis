"""Tests for the PE feature extractor."""

from __future__ import annotations

import pytest

from app.services.pe_features import (
    FEATURE_SCHEMA_VERSION,
    PEParseError,
    extract_features,
)
from tests.fixtures.pe_builder import (
    IMAGE_FILE_MACHINE_I386,
    IMAGE_NT_OPTIONAL_HDR32_MAGIC,
    build_minimal_pe,
)


def test_extract_features_on_minimal_pe():
    pe_bytes = build_minimal_pe()
    features = extract_features(pe_bytes)

    assert features.schema_version == FEATURE_SCHEMA_VERSION
    assert features.size_bytes == len(pe_bytes)
    assert len(features.sha256) == 64

    # COFF header round-trip
    assert features.machine == IMAGE_FILE_MACHINE_I386
    assert features.number_of_sections == 1

    # Optional header
    assert features.magic == IMAGE_NT_OPTIONAL_HDR32_MAGIC
    assert features.image_base == 0x00400000
    assert features.subsystem == 3  # CONSOLE

    # One section, named ".text"
    assert len(features.sections) == 1
    assert features.sections[0].name == ".text"
    # Payload was 64 NOP bytes → very low entropy.
    assert features.sections[0].entropy < 1.0

    # No imports / resources / signature wired into the minimal stub.
    assert features.imported_dll_count == 0
    assert features.imported_function_count == 0
    assert features.has_signature is False
    assert features.has_resources is False


def test_extract_features_high_entropy_section():
    # Pseudo-random payload → entropy should approach 8.0 bits/byte.
    import os

    payload = os.urandom(4096)
    pe_bytes = build_minimal_pe(section_payload=payload)
    features = extract_features(pe_bytes)
    assert features.sections[0].entropy > 7.0


def test_extract_features_rejects_garbage():
    with pytest.raises(PEParseError):
        extract_features(b"this is not a PE at all")


def test_extract_features_rejects_truncated_pe():
    pe_bytes = build_minimal_pe()
    # Lop off everything past the DOS header — pefile must refuse to parse.
    with pytest.raises(PEParseError):
        extract_features(pe_bytes[:64])


def test_to_dict_is_json_serializable():
    import json

    features = extract_features(build_minimal_pe())
    payload = features.to_dict()
    # Should round-trip through json without TypeError.
    json.dumps(payload)
    assert payload["schema_version"] == FEATURE_SCHEMA_VERSION
    assert isinstance(payload["sections"], list)
    assert payload["sections"][0]["name"] == ".text"
