"""Tests for the model registry: mock path, real path, manifest verification."""

from __future__ import annotations

import hashlib
import json
import pickle  # used to fabricate a fake artifact (S403 ignored project-wide for tests)

import pytest

from app.services.model_registry import (
    ModelManifestError,
    ModelRegistry,
    _MockPredictor,
    get_registry,
)
from app.services.pe_features import FEATURE_VECTOR_ORDER, extract_features
from tests.fixtures.pe_builder import build_minimal_pe


def test_mock_predictor_is_deterministic():
    p = _MockPredictor(model_id="rf-v1")
    vec = [float(i) for i in range(len(FEATURE_VECTOR_ORDER))]
    assert p.predict(vec) == p.predict(vec)


def test_mock_predictors_can_disagree():
    """Different model IDs produce independent predictions on the same vector.

    The disagreement view is one of the dashboard's most demo-able pieces;
    if mocks always agreed, the demo would feel broken.
    """
    rf = _MockPredictor(model_id="rf-v1", bias=-0.05)
    xgb = _MockPredictor(model_id="xgb-v1", bias=0.05)

    vectors = [extract_features(build_minimal_pe(section_payload=bytes([i] * 64))).to_vector()
               for i in range(8)]
    rf_labels = [rf.predict(v)[0] for v in vectors]
    xgb_labels = [xgb.predict(v)[0] for v in vectors]
    # At least one disagreement across 8 different inputs — otherwise the
    # bias is too small to be useful for the demo.
    assert any(a != b for a, b in zip(rf_labels, xgb_labels, strict=True))


def test_module_singleton_returns_models():
    registry = get_registry()
    models = registry.models()
    assert len(models) >= 2
    assert {m.entry.id for m in models} >= {"rf-v1", "xgb-v1"}
    assert registry.is_mock_mode is True  # default config has use_mock_models=True


def test_predict_all_returns_one_prediction_per_model():
    features = extract_features(build_minimal_pe())
    predictions = get_registry().predict_all(features)
    assert len(predictions) == len(get_registry().models())
    for pred in predictions:
        assert pred.label in ("malicious", "benign")
        assert pred.confidence > 0.0
        assert pred.latency_ms >= 0.0


def test_real_loader_refuses_sha_mismatch(tmp_path, monkeypatch):
    """A pickle whose SHA-256 isn't pinned must be refused — SECURITY.md."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    fake_artifact = artifacts_dir / "rf-v1.joblib"
    # joblib.load can swallow a plain pickle, so a fabricated one is fine
    # for the SHA check — we never reach `joblib.load` if the hash mismatches.
    fake_artifact.write_bytes(pickle.dumps({"not": "a real model"}))

    manifest_path = tmp_path / "MANIFEST.json"
    manifest_path.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "id": "rf-v1",
                        "family": "random_forest",
                        "filename": "rf-v1.joblib",
                        "sha256": "deadbeef" * 8,  # intentionally wrong
                        "trained_at": "2024-01-01T00:00:00Z",
                        "training_dataset": "test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "use_mock_models", False)
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "model_manifest_path", manifest_path)

    fresh = ModelRegistry()
    with pytest.raises(ModelManifestError, match="sha256 mismatch"):
        fresh.load()


def test_real_loader_refuses_schema_mismatch(tmp_path, monkeypatch):
    """Manifest schema version pinned to a different value must abort the load."""
    manifest_path = tmp_path / "MANIFEST.json"
    manifest_path.write_text(
        json.dumps({"feature_schema_version": "999.0.0", "models": []}),
        encoding="utf-8",
    )
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "use_mock_models", False)
    monkeypatch.setattr(settings, "model_manifest_path", manifest_path)
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    fresh = ModelRegistry()
    with pytest.raises(ModelManifestError, match="feature_schema_version"):
        fresh.load()


def test_real_loader_accepts_valid_sha(tmp_path, monkeypatch):
    """Sanity: when the SHA matches, loading proceeds (then fails on the
    pickle being not-an-sklearn-model, but that is past the SHA check)."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    fake_artifact = artifacts_dir / "rf-v1.joblib"
    payload = pickle.dumps({"not": "a real model"})
    fake_artifact.write_bytes(payload)
    real_sha = hashlib.sha256(payload).hexdigest()

    manifest_path = tmp_path / "MANIFEST.json"
    manifest_path.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "id": "rf-v1",
                        "family": "random_forest",
                        "filename": "rf-v1.joblib",
                        "sha256": real_sha,
                        "trained_at": "2024-01-01T00:00:00Z",
                        "training_dataset": "test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "use_mock_models", False)
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "model_manifest_path", manifest_path)

    fresh = ModelRegistry()
    # Past the SHA check joblib will happily unpickle the dict; the loader
    # then wraps it in _SklearnPredictor, which only fails when `.predict`
    # is called. Loading itself should succeed.
    loaded = fresh.load()
    assert len(loaded) == 1
    assert loaded[0].entry.id == "rf-v1"
    assert loaded[0].is_mock is False
