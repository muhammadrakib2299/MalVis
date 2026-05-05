"""Pydantic schemas for /explain.

Wire shape designed for a SHAP waterfall: each `ModelExplanation` carries
the prediction it explains, a base value, and an ordered list of
per-feature contributions sorted by absolute SHAP magnitude.

`is_mock` is a per-model flag, not a global one — once real artifacts
land, RF and XGBoost may flip from mock to real independently and the
frontend should be able to render them side-by-side honestly.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FeatureContribution(BaseModel):
    model_config = ConfigDict(frozen=True)

    feature: str
    value: float
    shap_value: float


class ModelExplanation(BaseModel):
    model_config = ConfigDict(frozen=True, protected_namespaces=())

    model_name: str
    is_mock: bool
    label: str
    confidence: float
    base_value: float
    contributions: list[FeatureContribution] = Field(default_factory=list)


class ExplainResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    sha256: str
    feature_schema_version: str
    explanations: list[ModelExplanation] = Field(default_factory=list)
