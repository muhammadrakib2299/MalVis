"""SHAP explanations — real (TreeExplainer) and mock (deterministic).

Two paths, same wire shape:

  - **Real**: builds a `shap.TreeExplainer` per loaded model on first use,
    caches it, and returns SHAP values for the feature vector. Tree
    explainers are deterministic; cached because TreeExplainer init is
    the expensive part, not the per-sample call.
  - **Mock**: deterministic per-feature contributions derived from the
    SHA-256 of the model id + feature vector. Lets the SHAP waterfall
    render before the trained pickles arrive, with `is_mock=True` so the
    UI can show a "demo data" banner. Honesty over a polished-but-fake
    chart.

The explanation is always returned with the prediction it explains, so
the frontend never has to correlate two endpoints to render the
waterfall.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from typing import Any

from app.schemas.explain import (
    ExplainResponse,
    FeatureContribution,
    ModelExplanation,
)
from app.services.model_registry import LoadedModel, get_registry
from app.services.pe_features import FEATURE_VECTOR_ORDER, PEFeatures

# Default top-N for the waterfall view. Capped to keep the payload small;
# the frontend can request more later via a query param if needed.
DEFAULT_TOP_N = 12


class ExplainerError(RuntimeError):
    """Raised when an explanation cannot be produced for a known model."""


# --- TreeExplainer cache -------------------------------------------------

_real_explainer_cache: dict[str, Any] = {}
_real_explainer_lock = threading.Lock()


def _get_real_explainer(model: LoadedModel) -> Any:
    cached = _real_explainer_cache.get(model.entry.id)
    if cached is not None:
        return cached
    with _real_explainer_lock:
        cached = _real_explainer_cache.get(model.entry.id)
        if cached is not None:
            return cached
        # Local import: shap is heavy and we don't want it on the
        # mock-only critical path or in unit tests that never call it.
        import shap  # noqa: PLC0415

        # `predictor.model` is the underlying sklearn/xgboost classifier
        # for `_SklearnPredictor`. Mock predictors don't get here because
        # `_explain_real` is only called when `model.is_mock` is False.
        underlying = getattr(model.predictor, "model", None)
        if underlying is None:
            raise ExplainerError(f"model {model.entry.id} has no underlying predictor")
        explainer = shap.TreeExplainer(underlying)
        _real_explainer_cache[model.entry.id] = explainer
        return explainer


# --- Public entry point --------------------------------------------------


@dataclass(frozen=True)
class _Contribution:
    feature: str
    value: float
    shap_value: float


def explain_features(
    features: PEFeatures,
    *,
    model_name: str | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> ExplainResponse:
    """Return per-model SHAP-style explanations for `features`.

    If `model_name` is given, only that model is explained. The response
    always echoes `is_mock` per model so the UI can flag synthetic data.
    """
    registry = get_registry()
    targets = [m for m in registry.models() if model_name is None or m.entry.id == model_name]
    if not targets:
        raise ExplainerError(f"unknown model: {model_name}")

    vector = features.to_vector()
    explanations: list[ModelExplanation] = []
    for model in targets:
        if model.is_mock:
            base, contribs = _explain_mock(model.entry.id, vector)
        else:
            base, contribs = _explain_real(model, vector)
        # Predicted label/confidence comes from the predictor itself so the
        # explanation is consistent with /scan output (same input → same call).
        label, confidence = model.predictor.predict(vector)
        explanations.append(
            ModelExplanation(
                model_name=model.entry.id,
                is_mock=model.is_mock,
                label=label,
                confidence=round(confidence, 4),
                base_value=round(base, 6),
                contributions=[
                    FeatureContribution(
                        feature=c.feature,
                        value=round(c.value, 6),
                        shap_value=round(c.shap_value, 6),
                    )
                    for c in _top_n(contribs, top_n)
                ],
            )
        )

    return ExplainResponse(
        sha256=features.sha256,
        feature_schema_version=features.schema_version,
        explanations=explanations,
    )


# --- Internal: real and mock generators ----------------------------------


def _explain_real(model: LoadedModel, vector: list[float]) -> tuple[float, list[_Contribution]]:
    import numpy as np  # noqa: PLC0415

    explainer = _get_real_explainer(model)
    x = np.asarray(vector, dtype=float).reshape(1, -1)
    raw = explainer.shap_values(x)

    # `shap_values` shape varies by model family:
    #   - binary classifier (sklearn RF): list of two arrays [class_0, class_1]
    #   - xgboost: single array of shape (n_samples, n_features)
    if isinstance(raw, list) and len(raw) == 2:
        shap_row = raw[1][0]
        base_value = float(np.atleast_1d(explainer.expected_value)[1])
    else:
        arr = np.asarray(raw)
        # If the array has a leading sample axis, drop it.
        shap_row = arr[0] if arr.ndim == 2 else arr
        ev = explainer.expected_value
        base_value = float(np.atleast_1d(ev)[-1])

    contributions = [
        _Contribution(feature=name, value=value, shap_value=float(shap_row[i]))
        for i, (name, value) in enumerate(zip(FEATURE_VECTOR_ORDER, vector, strict=True))
    ]
    return base_value, contributions


def _explain_mock(model_id: str, vector: list[float]) -> tuple[float, list[_Contribution]]:
    """Deterministic mock SHAP values.

    Hashes (model_id, feature_index, feature_value) into a signed
    contribution in [-1, 1]. Same input → same explanation. Spread is
    intentionally similar to a real SHAP waterfall so the UI looks right
    in screenshots; the `is_mock` flag is the truth label.
    """
    contributions: list[_Contribution] = []
    base_seed = hashlib.sha256(model_id.encode()).digest()
    base_value = (int.from_bytes(base_seed[:2], "big") / 0xFFFF - 0.5) * 0.6  # ≈ [-0.3, 0.3]

    for i, (name, value) in enumerate(zip(FEATURE_VECTOR_ORDER, vector, strict=True)):
        h = hashlib.sha256(f"{model_id}|{i}|{value:.4f}".encode()).digest()
        signed = (int.from_bytes(h[:4], "big") / 0xFFFFFFFF - 0.5) * 2.0  # ≈ [-1, 1]
        contributions.append(
            _Contribution(feature=name, value=value, shap_value=round(signed, 6))
        )
    return base_value, contributions


def _top_n(contribs: list[_Contribution], n: int) -> list[_Contribution]:
    """Top-N by absolute SHAP value, ties broken by feature name."""
    return sorted(contribs, key=lambda c: (-abs(c.shap_value), c.feature))[:n]
