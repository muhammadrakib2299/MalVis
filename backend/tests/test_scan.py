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
    """Second scan of the same bytes should skip the extractor entirely."""
    from app.routers import scan as scan_router
    from app.services import extractor as extractor_mod

    scan_router.get_scan_cache().clear()

    pe_bytes = build_minimal_pe()
    first = client.post(
        "/scan",
        files={"upload": ("sample.exe", pe_bytes, "application/octet-stream")},
    )
    assert first.status_code == 200

    # Replace the cached extractor with one that fails loudly. If the cache
    # is bypassed for a known SHA the second call will hit this and the
    # test will fail.
    class _Boom:
        def extract(self, _: bytes):
            raise AssertionError("extractor called on a cache hit")

    monkeypatch.setattr(extractor_mod, "_extractor_cache", _Boom())

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
