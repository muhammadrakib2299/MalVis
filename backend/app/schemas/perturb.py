"""Pydantic schemas for /perturb.

Wire shape designed for a slider/toggle UI: the client sends what it
already has (the feature vector or a flat features dict) plus a list of
perturbation specs, and gets back baseline + perturbed predictions plus
a per-model delta envelope so the diff renders without arithmetic on
the frontend.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.scan import FeatureResponse, ModelPrediction

PerturbOp = Literal["set", "delta", "scale", "toggle"]


class PerturbationSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    feature: str = Field(..., description="Feature name from /models.feature_order")
    op: PerturbOp
    value: float = 0.0


class PerturbRequest(BaseModel):
    """Request body. Either `features` or `feature_vector` must be supplied.

    `features` is the easier shape (round-trip what /scan returned).
    `feature_vector` is for clients that already cache the vector and want
    to skip the FeatureResponse → vector conversion.
    """

    model_config = ConfigDict(frozen=True, protected_namespaces=())

    features: FeatureResponse | None = None
    feature_vector: list[float] | None = None
    perturbations: list[PerturbationSpec] = Field(default_factory=list)
    model_name: str | None = None


class AppliedPerturbationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    feature: str
    op: PerturbOp
    before: float
    after: float


class PredictionDelta(BaseModel):
    model_config = ConfigDict(frozen=True, protected_namespaces=())

    model_name: str
    baseline_label: str
    perturbed_label: str
    label_flipped: bool
    confidence_delta: float


class PerturbResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    sha256: str | None = None
    feature_schema_version: str
    applied: list[AppliedPerturbationResponse] = Field(default_factory=list)
    baseline_predictions: list[ModelPrediction] = Field(default_factory=list)
    perturbed_predictions: list[ModelPrediction] = Field(default_factory=list)
    deltas: list[PredictionDelta] = Field(default_factory=list)
