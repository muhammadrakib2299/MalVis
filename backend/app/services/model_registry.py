"""Model registry: load, verify, and serve predictions.

Two paths share one interface:

  - **Real**: loads `*.joblib` artifacts from `artifacts/` after verifying
    every pickle's SHA-256 against `MANIFEST.json`. A pickle whose hash is
    not in the manifest is refused — that is the rule from `SECURITY.md`
    and the loader treats it as non-negotiable.
  - **Mock**: deterministic predictions derived from the SHA-256 of the
    feature vector. Used when `use_mock_models=True` *or* when the manifest
    is missing. Lets the frontend and the demo work end-to-end before the
    paper's trained pickles are recovered.

The registry is a lazy singleton. Loading happens on first access (not at
import time) so a bad manifest cannot block `/health` from coming up — the
`/ready` endpoint is the gate that exposes registry state honestly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.config import get_settings
from app.schemas.scan import ModelPrediction
from app.services.pe_features import (
    FEATURE_SCHEMA_VERSION,
    FEATURE_VECTOR_ORDER,
    PEFeatures,
)

log = logging.getLogger(__name__)


class ModelManifestError(RuntimeError):
    """Raised when a manifest entry refuses to load.

    Includes any SHA-256 mismatch, missing file, missing manifest, or
    schema-version mismatch. Caller treats this as fatal for that model
    only — other entries can still load.
    """


# --- Manifest schema -----------------------------------------------------


@dataclass(frozen=True)
class ManifestEntry:
    id: str
    family: str
    filename: str
    sha256: str
    trained_at: str
    training_dataset: str
    metrics: dict[str, float] = field(default_factory=dict)
    paper_citation: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManifestEntry:
        return cls(
            id=str(data["id"]),
            family=str(data["family"]),
            filename=str(data["filename"]),
            sha256=str(data["sha256"]).lower(),
            trained_at=str(data.get("trained_at", "")),
            training_dataset=str(data.get("training_dataset", "")),
            metrics={k: float(v) for k, v in (data.get("metrics") or {}).items()},
            paper_citation=str(data.get("paper_citation", "")),
            notes=str(data.get("notes", "")),
        )


@dataclass(frozen=True)
class LoadedModel:
    entry: ManifestEntry
    predictor: ModelPredictor
    is_mock: bool


# --- Predictor protocol ---------------------------------------------------


class ModelPredictor(Protocol):
    """Anything that turns a feature vector into a (label, confidence)."""

    def predict(self, vector: list[float]) -> tuple[str, float]: ...


@dataclass(frozen=True)
class _MockPredictor:
    """Deterministic mock: hash the vector + a model-specific salt.

    The same input always produces the same prediction, which keeps demos
    reproducible. Different model `id`s produce slightly different splits,
    so RF and XGBoost can disagree (the disagreement view is one of the
    most demo-able pieces of the dashboard — `TODO.md` Phase 3).
    """

    model_id: str
    bias: float = 0.0  # nudges the malicious/benign split per model

    def predict(self, vector: list[float]) -> tuple[str, float]:
        # Quantize the vector to keep tiny float jitter from flipping labels.
        quantized = ",".join(f"{v:.4f}" for v in vector)
        digest = hashlib.sha256(f"{self.model_id}|{quantized}".encode()).digest()
        # First two bytes → score in [0, 1).
        score = int.from_bytes(digest[:2], "big") / 0xFFFF
        score = min(max(score + self.bias, 0.0), 1.0)
        label = "malicious" if score >= 0.5 else "benign"
        # Confidence is distance from the decision boundary, scaled to [0.5, 1].
        confidence = 0.5 + abs(score - 0.5)
        return label, confidence


# --- Registry -------------------------------------------------------------


# Default mock manifest used when `use_mock_models` is on or no real
# manifest exists. Mirrors the example manifest in `artifacts/` so the
# frontend sees a stable model list either way.
_MOCK_MANIFEST_ENTRIES: tuple[ManifestEntry, ...] = (
    ManifestEntry(
        id="rf-v1",
        family="random_forest",
        filename="(mock)",
        sha256="0" * 64,
        trained_at="mock",
        training_dataset="mock",
        metrics={"f1": 0.0, "precision": 0.0, "recall": 0.0},
        paper_citation="(mock — replace once trained pickles are pinned in MANIFEST.json)",
        notes="Deterministic mock predictor — not a trained model.",
    ),
    ManifestEntry(
        id="xgb-v1",
        family="xgboost",
        filename="(mock)",
        sha256="0" * 64,
        trained_at="mock",
        training_dataset="mock",
        metrics={"f1": 0.0, "precision": 0.0, "recall": 0.0},
        paper_citation="(mock — replace once trained pickles are pinned in MANIFEST.json)",
        notes="Deterministic mock predictor — not a trained model.",
    ),
)


class ModelRegistry:
    """Holds loaded predictors and serves them through `predict_all`.

    Thread-safe lazy load: the first caller triggers the load under a lock,
    subsequent callers see the already-loaded list. Failures during load
    are not retried on the next call — a misconfigured manifest is a
    deploy-time problem and silently retrying would hide it.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._models: list[LoadedModel] | None = None
        self._load_error: Exception | None = None
        self._is_mock_mode = False

    @property
    def is_loaded(self) -> bool:
        return self._models is not None

    @property
    def is_mock_mode(self) -> bool:
        return self._is_mock_mode

    def load(self) -> list[LoadedModel]:
        """Load on first call; idempotent thereafter."""
        if self._models is not None:
            return self._models
        with self._lock:
            if self._models is not None:
                return self._models
            try:
                self._models = self._load_inner()
            except Exception as exc:
                self._load_error = exc
                raise
        return self._models

    def models(self) -> list[LoadedModel]:
        return self.load()

    def predict_all(self, features: PEFeatures) -> list[ModelPrediction]:
        """Run every loaded model on `features` and return predictions."""
        vector = features.to_vector()
        if len(vector) != len(FEATURE_VECTOR_ORDER):
            # Defensive: vectorizer drift would otherwise produce silent
            # garbage predictions. Fail loudly instead.
            raise RuntimeError(
                f"feature vector length mismatch: {len(vector)} vs "
                f"{len(FEATURE_VECTOR_ORDER)} (schema {FEATURE_SCHEMA_VERSION})"
            )
        results: list[ModelPrediction] = []
        for model in self.models():
            t0 = time.perf_counter()
            label, confidence = model.predictor.predict(vector)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            results.append(
                ModelPrediction(
                    model_name=model.entry.id,
                    label=label,
                    confidence=round(confidence, 4),
                    latency_ms=round(elapsed_ms, 3),
                )
            )
        return results

    # --- Internal -------------------------------------------------------

    def _load_inner(self) -> list[LoadedModel]:
        settings = get_settings()
        manifest_path = settings.model_manifest_path

        if settings.use_mock_models or not manifest_path.exists():
            log.info(
                "model_registry: loading mock predictors (use_mock=%s manifest_exists=%s)",
                settings.use_mock_models,
                manifest_path.exists(),
            )
            self._is_mock_mode = True
            return [
                LoadedModel(
                    entry=entry,
                    predictor=_MockPredictor(model_id=entry.id, bias=bias),
                    is_mock=True,
                )
                # Slight per-model bias so mock RF and mock XGBoost can
                # produce different verdicts on the same file.
                for entry, bias in zip(_MOCK_MANIFEST_ENTRIES, (-0.05, 0.05), strict=True)
            ]

        return self._load_real(manifest_path, settings.artifacts_dir)

    def _load_real(self, manifest_path: Path, artifacts_dir: Path) -> list[LoadedModel]:
        # Local import: keep joblib out of the import path for the mock-only
        # CI/test runs, which don't need scikit-learn or xgboost installed.
        import joblib  # noqa: PLC0415

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        # Optional but recommended: manifest pins the schema version.
        manifest_schema = manifest.get("feature_schema_version")
        if manifest_schema and manifest_schema != FEATURE_SCHEMA_VERSION:
            raise ModelManifestError(
                f"manifest feature_schema_version={manifest_schema} "
                f"does not match runtime {FEATURE_SCHEMA_VERSION}"
            )

        loaded: list[LoadedModel] = []
        for raw in manifest.get("models", []):
            entry = ManifestEntry.from_dict(raw)
            artifact_path = artifacts_dir / entry.filename
            if not artifact_path.exists():
                raise ModelManifestError(f"artifact missing on disk: {artifact_path}")

            data = artifact_path.read_bytes()
            actual_sha = hashlib.sha256(data).hexdigest()
            if actual_sha != entry.sha256:
                raise ModelManifestError(
                    f"sha256 mismatch for {entry.id}: "
                    f"manifest={entry.sha256} actual={actual_sha}"
                )

            model_obj = joblib.load(artifact_path)  # noqa: S301 — verified above
            loaded.append(
                LoadedModel(
                    entry=entry,
                    predictor=_SklearnPredictor(model_obj),
                    is_mock=False,
                )
            )
        return loaded


@dataclass(frozen=True)
class _SklearnPredictor:
    """Thin adapter for scikit-learn / xgboost classifiers.

    Expects the loaded object to implement `predict` and either
    `predict_proba` or `decision_function`. We avoid `numpy` at import time
    by deferring the cast.
    """

    model: Any

    def predict(self, vector: list[float]) -> tuple[str, float]:
        import numpy as np  # noqa: PLC0415

        x = np.asarray(vector, dtype=float).reshape(1, -1)
        # Probabilistic confidence if available; otherwise fall back to a
        # signed decision-function squashed into [0,1] via a logistic.
        if hasattr(self.model, "predict_proba"):
            proba = self.model.predict_proba(x)[0]
            class_idx = int(np.argmax(proba))
            confidence = float(proba[class_idx])
        elif hasattr(self.model, "decision_function"):
            score = float(self.model.decision_function(x)[0])
            confidence = 1.0 / (1.0 + np.exp(-abs(score)))
            class_idx = 1 if score >= 0 else 0
        else:
            class_idx = int(self.model.predict(x)[0])
            confidence = 1.0  # honest: model gave no confidence signal
        label = "malicious" if class_idx == 1 else "benign"
        return label, confidence


# --- Module-level singleton ----------------------------------------------

_registry = ModelRegistry()


def get_registry() -> ModelRegistry:
    return _registry
