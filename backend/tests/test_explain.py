"""Tests for /explain and the explanation service in mock mode."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from app.main import app
from app.services.explain import explain_features
from app.services.pe_features import FEATURE_VECTOR_ORDER, extract_features
from tests.fixtures.pe_builder import build_minimal_pe

client = TestClient(app)


def test_explain_features_returns_one_explanation_per_model():
    features = extract_features(build_minimal_pe())
    response = explain_features(features)
    assert response.sha256 == features.sha256
    assert len(response.explanations) >= 2
    for exp in response.explanations:
        assert exp.is_mock is True
        assert exp.label in ("malicious", "benign")
        assert 0.5 <= exp.confidence <= 1.0
        # Default top_n is 12; capped by the feature count.
        assert len(exp.contributions) == min(12, len(FEATURE_VECTOR_ORDER))
        # Sorted by absolute SHAP magnitude.
        magnitudes = [abs(c.shap_value) for c in exp.contributions]
        assert magnitudes == sorted(magnitudes, reverse=True)


def test_explain_is_deterministic():
    features = extract_features(build_minimal_pe())
    a = explain_features(features)
    b = explain_features(features)
    assert a.model_dump() == b.model_dump()


def test_explain_filter_by_model_name():
    features = extract_features(build_minimal_pe())
    response = explain_features(features, model_name="rf-v1")
    assert len(response.explanations) == 1
    assert response.explanations[0].model_name == "rf-v1"


def test_explain_endpoint_happy_path():
    pe_bytes = build_minimal_pe()
    expected_hash = hashlib.sha256(pe_bytes).hexdigest()

    response = client.post(
        "/explain",
        files={"upload": ("sample.exe", pe_bytes, "application/octet-stream")},
        data={"top_n": "5"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sha256"] == expected_hash
    assert len(body["explanations"]) >= 2
    for exp in body["explanations"]:
        assert exp["is_mock"] is True
        assert len(exp["contributions"]) == 5


def test_explain_endpoint_filter_by_model_name():
    response = client.post(
        "/explain",
        files={"upload": ("sample.exe", build_minimal_pe(), "application/octet-stream")},
        data={"model_name": "xgb-v1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["explanations"]) == 1
    assert body["explanations"][0]["model_name"] == "xgb-v1"


def test_explain_endpoint_unknown_model_returns_404():
    response = client.post(
        "/explain",
        files={"upload": ("sample.exe", build_minimal_pe(), "application/octet-stream")},
        data={"model_name": "does-not-exist"},
    )
    assert response.status_code == 404


def test_explain_endpoint_rejects_non_pe():
    response = client.post(
        "/explain",
        files={"upload": ("not.html", b"<html>nope</html>", "text/html")},
    )
    assert response.status_code == 400


# --- GET /explain/{sha256} -------------------------------------------------


def test_explain_by_hash_returns_explanations_for_sample():
    """A gallery sample's permalink hash should yield SHAP attributions."""
    from app.services.samples import list_samples

    sample = list_samples()[0]
    response = client.get(f"/explain/{sample.sha256}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sha256"] == sample.sha256
    assert len(body["explanations"]) >= 1
    for exp in body["explanations"]:
        # Mock mode: every explanation is_mock True until real artifacts land.
        assert isinstance(exp["is_mock"], bool)
        assert len(exp["contributions"]) >= 1


def test_explain_by_hash_supports_model_filter_and_top_n():
    from app.services.samples import list_samples

    sample = list_samples()[0]
    response = client.get(
        f"/explain/{sample.sha256}",
        params={"model_name": "rf-v1", "top_n": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["explanations"]) == 1
    assert body["explanations"][0]["model_name"] == "rf-v1"
    assert len(body["explanations"][0]["contributions"]) == 5


def test_explain_by_hash_unknown_returns_404():
    """Hash that isn't a sample → 404 (uploads aren't retained)."""
    response = client.get(f"/explain/{'b' * 64}")
    assert response.status_code == 404


def test_explain_by_hash_rejects_non_hex_path():
    response = client.get("/explain/not-a-real-sha")
    assert response.status_code in (404, 422)
