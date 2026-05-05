"""Tests for the sample registry, /samples endpoints, and /scan/{sha256} lookup."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from app.main import app
from app.services.samples import (
    get_sample_by_hash,
    get_sample_bytes,
    list_samples,
)

client = TestClient(app)


# --- registry --------------------------------------------------------------


def test_registry_lists_expected_ids():
    ids = {s.id for s in list_samples()}
    assert {"minimal-clean", "high-entropy", "large-code"} <= ids


def test_each_builder_produces_a_parseable_pe():
    from app.services.pe_features import extract_features

    for info in list_samples():
        body = get_sample_bytes(info.id)
        features = extract_features(body)
        assert features.sha256 == info.sha256


def test_sha256_is_deterministic_across_calls():
    """Same builder twice → same bytes → same SHA. Permalinks depend on this."""
    first = {info.id: info.sha256 for info in list_samples()}
    second = {info.id: info.sha256 for info in list_samples()}
    assert first == second


def test_get_sample_by_hash_round_trip():
    info = list_samples()[0]
    matched = get_sample_by_hash(info.sha256)
    assert matched is not None
    assert matched.id == info.id


def test_get_sample_by_hash_unknown_returns_none():
    assert get_sample_by_hash("0" * 64) is None


# --- HTTP: /samples --------------------------------------------------------


def test_get_samples_returns_metadata():
    response = client.get("/samples")
    assert response.status_code == 200
    body = response.json()
    assert "samples" in body
    ids = {s["id"] for s in body["samples"]}
    assert {"minimal-clean", "high-entropy", "large-code"} <= ids
    for s in body["samples"]:
        assert len(s["sha256"]) == 64
        assert s["size_bytes"] > 0


def test_post_sample_scan_happy_path():
    response = client.post("/samples/minimal-clean/scan")
    assert response.status_code == 200
    body = response.json()
    assert len(body["sha256"]) == 64
    assert len(body["predictions"]) >= 2
    # The mock predictors always return at least one entry per registered model.
    for pred in body["predictions"]:
        assert pred["label"] in ("malicious", "benign")


def test_post_sample_scan_unknown_returns_404():
    response = client.post("/samples/does-not-exist/scan")
    assert response.status_code == 404


# --- HTTP: /scan/{sha256} --------------------------------------------------


def test_lookup_scan_returns_cached_after_post():
    """Posting a sample warms the cache; a follow-up lookup hits it."""
    from app.routers.scan import get_scan_cache

    get_scan_cache().clear()
    body = get_sample_bytes("minimal-clean")
    sha = hashlib.sha256(body).hexdigest()

    # Cold: cache empty, sample fallback computes from registry.
    cold = client.get(f"/scan/{sha}")
    assert cold.status_code == 200

    # Warm: now cached.
    warm = client.get(f"/scan/{sha}")
    assert warm.status_code == 200
    assert warm.json() == cold.json()


def test_lookup_scan_returns_404_for_unknown_hash():
    """A SHA-256 that isn't in cache and isn't a sample → 404."""
    from app.routers.scan import get_scan_cache

    get_scan_cache().clear()
    response = client.get(f"/scan/{'a' * 64}")
    assert response.status_code == 404


def test_lookup_scan_rejects_non_hex_path():
    """The Path pattern must reject anything that isn't 64 hex chars."""
    response = client.get("/scan/not-a-real-sha")
    assert response.status_code in (404, 422)
