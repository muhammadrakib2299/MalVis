"""Tests for the perturbation service and POST /perturb."""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.pe_features import FEATURE_VECTOR_ORDER, extract_features
from app.services.perturb import (
    MAX_PERTURBATIONS_PER_REQUEST,
    Perturbation,
    PerturbValidationError,
    apply_perturbations,
)
from tests.fixtures.pe_builder import build_minimal_pe

client = TestClient(app)


def _baseline_vector() -> list[float]:
    return extract_features(build_minimal_pe()).to_vector()


# --- service-level ---------------------------------------------------------


def test_set_op_replaces_value():
    vec = _baseline_vector()
    result = apply_perturbations(vec, [Perturbation("imported_dll_count", "set", 7.0)])
    idx = FEATURE_VECTOR_ORDER.index("imported_dll_count")
    assert result.applied[0].after == 7.0
    # The function takes a list copy internally, so the caller's vector is untouched.
    assert vec[idx] == 0.0


def test_delta_op_adds_value():
    vec = _baseline_vector()
    idx = FEATURE_VECTOR_ORDER.index("size_of_code")
    before = vec[idx]
    result = apply_perturbations(vec, [Perturbation("size_of_code", "delta", 100.0)])
    assert result.applied[0].before == before
    assert result.applied[0].after == before + 100.0


def test_scale_op_multiplies_value():
    vec = _baseline_vector()
    idx = FEATURE_VECTOR_ORDER.index("size_of_image")
    before = vec[idx]
    result = apply_perturbations(vec, [Perturbation("size_of_image", "scale", 2.0)])
    assert result.applied[0].after == before * 2.0


def test_toggle_op_flips_boolean_feature():
    vec = _baseline_vector()
    idx = FEATURE_VECTOR_ORDER.index("has_signature")
    assert vec[idx] == 0.0
    result = apply_perturbations(vec, [Perturbation("has_signature", "toggle")])
    assert result.applied[0].after == 1.0
    # Second toggle puts it back.
    result2 = apply_perturbations(
        vec,
        [Perturbation("has_signature", "toggle"), Perturbation("has_signature", "toggle")],
    )
    assert result2.applied[1].after == 0.0


def test_toggle_rejects_non_boolean_feature():
    vec = _baseline_vector()
    with pytest.raises(PerturbValidationError, match="toggle is only valid"):
        apply_perturbations(vec, [Perturbation("size_of_code", "toggle")])


def test_unknown_feature_rejected():
    vec = _baseline_vector()
    with pytest.raises(PerturbValidationError, match="unknown feature"):
        apply_perturbations(vec, [Perturbation("nonexistent_feature", "set", 1.0)])


def test_nan_inf_value_rejected():
    vec = _baseline_vector()
    with pytest.raises(PerturbValidationError):
        apply_perturbations(vec, [Perturbation("size_of_code", "set", float("nan"))])
    with pytest.raises(PerturbValidationError):
        apply_perturbations(vec, [Perturbation("size_of_code", "set", math.inf)])


def test_perturbation_count_capped():
    vec = _baseline_vector()
    too_many = [
        Perturbation("size_of_code", "delta", 1.0)
        for _ in range(MAX_PERTURBATIONS_PER_REQUEST + 1)
    ]
    with pytest.raises(PerturbValidationError, match="too many perturbations"):
        apply_perturbations(vec, too_many)


def test_baseline_predictions_match_registry():
    """Baseline predictions in the result should match what /scan would return."""
    from app.services.model_registry import get_registry

    features = extract_features(build_minimal_pe())
    expected = get_registry().predict_all(features)
    result = apply_perturbations(features.to_vector(), [])
    expected_pairs = [(p.model_name, p.label, p.confidence) for p in expected]
    actual_pairs = [(p.model_name, p.label, p.confidence) for p in result.baseline_predictions]
    assert actual_pairs == expected_pairs


def test_model_name_filter_returns_one_model():
    vec = _baseline_vector()
    result = apply_perturbations(vec, [], model_name="rf-v1")
    assert len(result.baseline_predictions) == 1
    assert result.baseline_predictions[0].model_name == "rf-v1"


def test_model_name_unknown_rejected():
    vec = _baseline_vector()
    with pytest.raises(PerturbValidationError, match="unknown model"):
        apply_perturbations(vec, [], model_name="ghost")


def test_baseline_vector_length_validated():
    with pytest.raises(PerturbValidationError, match="vector length"):
        apply_perturbations([1.0, 2.0, 3.0], [])


# --- HTTP-level ------------------------------------------------------------


def _scan_payload() -> dict:
    """Drive the request body via /scan so the wire shape stays in sync."""
    pe_bytes = build_minimal_pe()
    response = client.post(
        "/scan",
        files={"upload": ("sample.exe", pe_bytes, "application/octet-stream")},
    )
    assert response.status_code == 200
    return response.json()


def test_endpoint_happy_path_with_features_payload():
    scanned = _scan_payload()
    response = client.post(
        "/perturb",
        json={
            "features": scanned["features"],
            "perturbations": [{"feature": "imported_dll_count", "op": "set", "value": 50}],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sha256"] == scanned["sha256"]
    assert len(body["applied"]) == 1
    assert body["applied"][0]["after"] == 50.0
    assert len(body["baseline_predictions"]) == len(body["perturbed_predictions"])
    assert len(body["deltas"]) == len(body["baseline_predictions"])
    for delta in body["deltas"]:
        assert isinstance(delta["label_flipped"], bool)


def test_endpoint_with_feature_vector_payload():
    vec = _baseline_vector()
    response = client.post(
        "/perturb",
        json={
            "feature_vector": vec,
            "perturbations": [{"feature": "has_signature", "op": "toggle"}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sha256"] is None  # no sha when only a vector is provided
    assert body["applied"][0]["before"] == 0.0
    assert body["applied"][0]["after"] == 1.0


def test_endpoint_requires_features_or_vector():
    response = client.post("/perturb", json={"perturbations": []})
    assert response.status_code == 422


def test_endpoint_unknown_feature_returns_422():
    vec = _baseline_vector()
    response = client.post(
        "/perturb",
        json={
            "feature_vector": vec,
            "perturbations": [{"feature": "definitely_not_a_real_feature", "op": "set", "value": 1}],
        },
    )
    assert response.status_code == 422


def test_endpoint_wrong_vector_length_returns_422():
    response = client.post(
        "/perturb",
        json={"feature_vector": [0.0, 1.0, 2.0], "perturbations": []},
    )
    assert response.status_code == 422


def test_endpoint_model_name_filter():
    vec = _baseline_vector()
    response = client.post(
        "/perturb",
        json={"feature_vector": vec, "perturbations": [], "model_name": "xgb-v1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert {p["model_name"] for p in body["baseline_predictions"]} == {"xgb-v1"}
