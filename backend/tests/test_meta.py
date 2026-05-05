"""Tests for /models and /ready."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.pe_features import FEATURE_SCHEMA_VERSION, FEATURE_VECTOR_ORDER

client = TestClient(app)


def test_models_lists_registered_predictors():
    resp = client.get("/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["feature_schema_version"] == FEATURE_SCHEMA_VERSION
    assert body["feature_count"] == len(FEATURE_VECTOR_ORDER)
    assert body["mock_mode"] is True
    ids = {m["id"] for m in body["models"]}
    assert ids == {"rf-v1", "xgb-v1"}
    for m in body["models"]:
        assert m["is_mock"] is True
        assert "metrics" in m
        assert "paper_citation" in m


def test_ready_returns_200_when_registry_loads():
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["mock_mode"] is True
    assert body["model_count"] >= 2
    assert body["feature_schema_version"] == FEATURE_SCHEMA_VERSION
