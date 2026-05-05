"""Adversarial perturbation simulator.

Operates on the *feature vector*, not the PE bytes. The dashboard uses
this to drive sliders and toggle switches — moving a slider should produce
a fresh prediction in the time it takes to round-trip JSON, which is
nowhere near affordable if every move re-uploaded a binary.

Threat-model note: this endpoint takes user-controlled numbers, never
user-controlled binaries. The validation surface is small (finite floats,
known feature names, bounded perturbation list) and entirely
client-controlled — no parser is downstream of it.

Operations:
  - **set**: replace the feature value with `value`
  - **delta**: add `value` to the current value
  - **scale**: multiply the current value by `value`
  - **toggle**: for boolean-encoded features (has_signature, has_resources,
    has_debug, has_tls), flip 0 ↔ 1; equivalent to `set` but friendlier
    for the toggle-switch UI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from app.schemas.scan import ModelPrediction
from app.services.model_registry import get_registry
from app.services.pe_features import FEATURE_VECTOR_ORDER

# Plenty of headroom for entropies, sizes, and hashes; rejects pathological
# values that would push numpy into NaN territory or hide a logic bug as a
# huge magnitude.
MAX_ABS_VALUE = 1.0e12
MAX_PERTURBATIONS_PER_REQUEST = 64

PerturbOp = Literal["set", "delta", "scale", "toggle"]
_BOOL_FEATURES = frozenset({"has_signature", "has_resources", "has_debug", "has_tls"})


class PerturbValidationError(ValueError):
    """Raised when a perturbation spec is malformed.

    Routers translate this to 422. The exception is *only* raised on
    user-controlled input that we refuse to accept; downstream errors
    bubble up unchanged.
    """


@dataclass(frozen=True)
class Perturbation:
    feature: str
    op: PerturbOp
    value: float = 0.0


@dataclass(frozen=True)
class AppliedPerturbation:
    feature: str
    op: PerturbOp
    before: float
    after: float


@dataclass(frozen=True)
class PerturbResult:
    baseline_predictions: list[ModelPrediction]
    perturbed_predictions: list[ModelPrediction]
    applied: list[AppliedPerturbation]


def _index_for_feature(name: str) -> int:
    try:
        return FEATURE_VECTOR_ORDER.index(name)
    except ValueError as exc:
        raise PerturbValidationError(f"unknown feature: {name}") from exc


def _check_finite(value: float, label: str) -> float:
    if not math.isfinite(value):
        raise PerturbValidationError(f"{label} must be a finite number")
    if abs(value) > MAX_ABS_VALUE:
        raise PerturbValidationError(f"{label} magnitude exceeds {MAX_ABS_VALUE}")
    return float(value)


def _apply_one(vector: list[float], spec: Perturbation) -> AppliedPerturbation:
    idx = _index_for_feature(spec.feature)
    before = vector[idx]
    op = spec.op

    if op == "set":
        after = _check_finite(spec.value, "set value")
    elif op == "delta":
        after = before + _check_finite(spec.value, "delta value")
        _check_finite(after, "post-delta value")
    elif op == "scale":
        scale = _check_finite(spec.value, "scale value")
        after = before * scale
        _check_finite(after, "post-scale value")
    elif op == "toggle":
        if spec.feature not in _BOOL_FEATURES:
            raise PerturbValidationError(
                f"toggle is only valid for boolean features {sorted(_BOOL_FEATURES)}"
            )
        after = 0.0 if before >= 0.5 else 1.0
    else:  # pragma: no cover — Pydantic Literal narrows this upstream
        raise PerturbValidationError(f"unknown op: {op}")

    vector[idx] = after
    return AppliedPerturbation(feature=spec.feature, op=op, before=before, after=after)


def apply_perturbations(
    baseline_vector: list[float],
    perturbations: list[Perturbation],
    *,
    model_name: str | None = None,
) -> PerturbResult:
    """Run the registry on `baseline_vector`, apply perturbations, run again.

    The baseline vector is treated as ground truth — we don't recompute it
    from scratch, so the predictions reported here exactly match what
    `/scan` returned for the same vector. That's important: a user looking
    at a "before" prediction in the UI and a different "before" here would
    rightly be confused.
    """
    if len(baseline_vector) != len(FEATURE_VECTOR_ORDER):
        raise PerturbValidationError(
            f"feature vector length {len(baseline_vector)} does not match "
            f"schema length {len(FEATURE_VECTOR_ORDER)}"
        )
    if len(perturbations) > MAX_PERTURBATIONS_PER_REQUEST:
        raise PerturbValidationError(
            f"too many perturbations: {len(perturbations)} > {MAX_PERTURBATIONS_PER_REQUEST}"
        )

    for i, v in enumerate(baseline_vector):
        _check_finite(float(v), f"baseline_vector[{i}]")

    registry = get_registry()
    targets = [m for m in registry.models() if model_name is None or m.entry.id == model_name]
    if not targets:
        raise PerturbValidationError(f"unknown model: {model_name}")

    def _predict(vec: list[float]) -> list[ModelPrediction]:
        # Delegate via registry.predict_all when no filter, otherwise inline
        # the per-model path so we honor the model_name filter without
        # mutating registry state.
        if model_name is None:
            return _predict_all_through_registry(vec)
        out: list[ModelPrediction] = []
        import time

        for model in targets:
            t0 = time.perf_counter()
            label, confidence = model.predictor.predict(vec)
            elapsed = (time.perf_counter() - t0) * 1000.0
            out.append(
                ModelPrediction(
                    model_name=model.entry.id,
                    label=label,
                    confidence=round(confidence, 4),
                    latency_ms=round(elapsed, 3),
                )
            )
        return out

    baseline_predictions = _predict(list(baseline_vector))

    working = list(baseline_vector)
    applied: list[AppliedPerturbation] = []
    for spec in perturbations:
        applied.append(_apply_one(working, spec))

    perturbed_predictions = _predict(working)

    return PerturbResult(
        baseline_predictions=baseline_predictions,
        perturbed_predictions=perturbed_predictions,
        applied=applied,
    )


def _predict_all_through_registry(vector: list[float]) -> list[ModelPrediction]:
    """Path through registry.predict_all without going via PEFeatures.

    `predict_all` expects a `PEFeatures`; for perturbation we already have
    the vector and don't need the dataclass. We replicate the loop here
    rather than synthesizing a fake PEFeatures (which would lie about
    `sha256`).
    """
    import time

    out: list[ModelPrediction] = []
    for model in get_registry().models():
        t0 = time.perf_counter()
        label, confidence = model.predictor.predict(vector)
        elapsed = (time.perf_counter() - t0) * 1000.0
        out.append(
            ModelPrediction(
                model_name=model.entry.id,
                label=label,
                confidence=round(confidence, 4),
                latency_ms=round(elapsed, 3),
            )
        )
    return out
