"""Metadata endpoints: /models and /ready.

`/health` (in main.py) is liveness — it answers "is the process up?".
`/ready` is readiness — it answers "can the process actually serve a
prediction?". Mixing them would mean restarts cascade into 503s while
models warm up, which is why they are separate.
"""

# NOTE: see scan.py / explain.py / perturb.py / samples.py for why this
# file does NOT use `from __future__ import annotations`.
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.services.model_registry import get_registry
from app.services.pe_features import FEATURE_SCHEMA_VERSION, FEATURE_VECTOR_ORDER

router = APIRouter(tags=["meta"])


class ModelInfo(BaseModel):
    model_config = ConfigDict(frozen=True, protected_namespaces=())

    id: str
    family: str
    is_mock: bool
    trained_at: str
    training_dataset: str
    metrics: dict[str, float]
    paper_citation: str
    notes: str


class ModelsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    feature_schema_version: str
    feature_count: int
    feature_order: list[str] = Field(default_factory=list)
    mock_mode: bool
    models: list[ModelInfo]


@router.get("/models", response_model=ModelsResponse)
def list_models() -> ModelsResponse:
    """List loaded models and the feature contract they were trained on.

    Triggers a registry load on first hit. The frontend uses this to render
    the "Built on" model-card panel and to know whether to surface a
    "running on mock predictions" banner during the demo.
    """
    registry = get_registry()
    loaded = registry.models()
    return ModelsResponse(
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        feature_count=len(FEATURE_VECTOR_ORDER),
        feature_order=list(FEATURE_VECTOR_ORDER),
        mock_mode=registry.is_mock_mode,
        models=[
            ModelInfo(
                id=m.entry.id,
                family=m.entry.family,
                is_mock=m.is_mock,
                trained_at=m.entry.trained_at,
                training_dataset=m.entry.training_dataset,
                metrics=m.entry.metrics,
                paper_citation=m.entry.paper_citation,
                notes=m.entry.notes,
            )
            for m in loaded
        ],
    )


@router.get("/ready")
def ready() -> dict[str, object]:
    """Readiness probe — 200 once the model registry has loaded.

    Triggers the lazy load on first hit. If loading fails (bad manifest,
    sha mismatch), this returns 503 with a sanitized detail; orchestrators
    use it to keep traffic away until the deploy is healthy.
    """
    registry = get_registry()
    try:
        models = registry.models()
    except Exception as exc:  # we sanitize the message before surfacing
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"registry not ready: {type(exc).__name__}",
        ) from exc

    return {
        "status": "ready",
        "mock_mode": registry.is_mock_mode,
        "model_count": len(models),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
    }
