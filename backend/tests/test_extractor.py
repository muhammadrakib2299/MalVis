"""Tests for the extractor abstraction and the standalone worker.

These tests run the worker via `subprocess.run` with the *current* Python
interpreter — no Docker required. The Dockerfile.extractor production
artifact is the same code, so these tests cover its semantics too.
"""

from __future__ import annotations

import json
import subprocess  # noqa: S404 — worker is invoked exactly the way production does
import sys
from pathlib import Path

import pytest

from app.services.extractor import (
    InProcessExtractor,
    SubprocessExtractor,
    _features_from_dict,
    get_extractor,
    reset_extractor_cache,
)
from app.services.pe_features import PEParseError, extract_features
from tests.fixtures.pe_builder import build_minimal_pe

REPO_BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_worker(stdin: bytes, *, timeout: float = 15.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "app.extractor_worker"],
        input=stdin,
        capture_output=True,
        timeout=timeout,
        check=False,
        cwd=REPO_BACKEND_DIR,
    )


# --- worker protocol -------------------------------------------------------


def test_worker_emits_envelope_on_valid_pe():
    proc = _run_worker(build_minimal_pe())
    assert proc.returncode == 0, proc.stderr
    envelope = json.loads(proc.stdout)
    assert envelope["ok"] is True
    assert envelope["features"]["number_of_sections"] == 1
    assert envelope["features"]["sections"][0]["name"] == ".text"


def test_worker_returns_2_on_parse_error():
    proc = _run_worker(b"not a PE")
    assert proc.returncode == 2
    envelope = json.loads(proc.stdout)
    assert envelope["ok"] is False
    assert "error" in envelope


def test_worker_returns_2_on_empty_input():
    proc = _run_worker(b"")
    assert proc.returncode == 2
    envelope = json.loads(proc.stdout)
    assert envelope["ok"] is False


# --- in-process extractor --------------------------------------------------


def test_inprocess_matches_extract_features_directly():
    pe_bytes = build_minimal_pe()
    a = InProcessExtractor().extract(pe_bytes)
    b = extract_features(pe_bytes)
    assert a.to_dict() == b.to_dict()


def test_inprocess_propagates_parse_error():
    with pytest.raises(PEParseError):
        InProcessExtractor().extract(b"garbage")


# --- subprocess extractor --------------------------------------------------


def test_subprocess_returns_same_features_as_inprocess():
    pe_bytes = build_minimal_pe()
    inproc = InProcessExtractor().extract(pe_bytes)
    sub = SubprocessExtractor().extract(pe_bytes)
    # PEFeatures dataclasses are frozen and compare structurally — but the
    # `sections` list compares by SectionFeatures equality which works because
    # SectionFeatures is also frozen. Compare via to_dict for clarity in the
    # diff if this ever fails.
    assert sub.to_dict() == inproc.to_dict()


def test_subprocess_raises_pe_parse_error_for_garbage():
    with pytest.raises(PEParseError):
        SubprocessExtractor().extract(b"clearly not a PE file")


def test_subprocess_raises_pe_parse_error_for_empty():
    with pytest.raises(PEParseError):
        SubprocessExtractor().extract(b"")


# --- features-from-dict round trip ----------------------------------------


def test_features_from_dict_round_trips():
    original = extract_features(build_minimal_pe())
    rebuilt = _features_from_dict(original.to_dict())
    assert rebuilt.to_dict() == original.to_dict()


# --- factory --------------------------------------------------------------


def test_factory_returns_inprocess_by_default():
    reset_extractor_cache()
    try:
        assert isinstance(get_extractor(), InProcessExtractor)
    finally:
        reset_extractor_cache()


def test_factory_returns_subprocess_when_configured(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "extractor_strategy", "subprocess")
    reset_extractor_cache()
    try:
        assert isinstance(get_extractor(), SubprocessExtractor)
    finally:
        reset_extractor_cache()


def test_factory_rejects_unknown_strategy(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "extractor_strategy", "voodoo")
    reset_extractor_cache()
    try:
        with pytest.raises(ValueError, match="unknown extractor_strategy"):
            get_extractor()
    finally:
        reset_extractor_cache()
