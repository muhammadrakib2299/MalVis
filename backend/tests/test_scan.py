"""End-to-end tests for POST /scan."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from app.main import app
from tests.fixtures.pe_builder import build_minimal_pe

client = TestClient(app)


def test_scan_happy_path_returns_features():
    pe_bytes = build_minimal_pe()
    expected_hash = hashlib.sha256(pe_bytes).hexdigest()

    response = client.post(
        "/scan",
        files={"upload": ("sample.exe", pe_bytes, "application/octet-stream")},
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["sha256"] == expected_hash
    assert body["features"]["sha256"] == expected_hash
    assert body["features"]["number_of_sections"] == 1
    assert body["features"]["sections"][0]["name"] == ".text"
    # Two mock predictors registered (rf-v1, xgb-v1) — see model_registry.
    assert len(body["predictions"]) == 2
    pred_ids = {p["model_name"] for p in body["predictions"]}
    assert pred_ids == {"rf-v1", "xgb-v1"}
    for p in body["predictions"]:
        assert p["label"] in ("malicious", "benign")
        assert 0.5 <= p["confidence"] <= 1.0


def test_scan_rejects_non_pe():
    response = client.post(
        "/scan",
        files={"upload": ("not.html", b"<html>nope</html>", "text/html")},
    )
    assert response.status_code == 400


def test_scan_rejects_oversize(monkeypatch):
    from app.security import upload as upload_mod

    monkeypatch.setattr(upload_mod._settings, "max_upload_bytes", 32)
    pe_bytes = build_minimal_pe()  # well over 32 bytes
    response = client.post(
        "/scan",
        files={"upload": ("big.exe", pe_bytes, "application/octet-stream")},
    )
    assert response.status_code == 413


def test_scan_second_call_hits_cache(monkeypatch):
    """Second scan of the same bytes should skip extract_features entirely."""
    from app.routers import scan as scan_router

    scan_router.get_scan_cache().clear()

    pe_bytes = build_minimal_pe()
    first = client.post(
        "/scan",
        files={"upload": ("sample.exe", pe_bytes, "application/octet-stream")},
    )
    assert first.status_code == 200

    # Patch the binding scan.py already pulled in. If the cache is bypassed
    # the second call will hit this and fail loudly.
    def _explode(_: bytes):
        raise AssertionError("extract_features called on a cache hit")

    monkeypatch.setattr(scan_router, "extract_features", _explode)

    second = client.post(
        "/scan",
        files={"upload": ("sample.exe", pe_bytes, "application/octet-stream")},
    )
    assert second.status_code == 200
    assert second.json() == first.json()


def test_scan_rejects_truncated_pe_with_400():
    # MZ magic passes but pefile cannot parse → PEParseError → 400.
    response = client.post(
        "/scan",
        files={"upload": ("trunc.exe", b"MZ" + b"\x00" * 64, "application/octet-stream")},
    )
    assert response.status_code == 400
