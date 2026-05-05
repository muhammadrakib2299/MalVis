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
    # Predictions are stubbed until the model registry lands.
    assert body["predictions"] == []


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


def test_scan_rejects_truncated_pe_with_400():
    # MZ magic passes but pefile cannot parse → PEParseError → 400.
    response = client.post(
        "/scan",
        files={"upload": ("trunc.exe", b"MZ" + b"\x00" * 64, "application/octet-stream")},
    )
    assert response.status_code == 400
