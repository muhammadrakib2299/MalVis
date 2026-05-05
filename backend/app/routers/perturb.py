"""POST /perturb — adversarial perturbation simulator.

Takes a baseline feature set (or vector), applies perturbations, returns
baseline and perturbed predictions plus a per-model diff envelope.
Operates on numbers only — no PE bytes downstream of this endpoint, so
the validation surface is small and the threat model is tight.

Rate limit is looser than /scan (30/min) because this is the slider-UI
path: a user dragging a slider can fire several requests per second,
but it's cheap (just two passes through the registry, no parser).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.perturb import (
    AppliedPerturbationResponse,
    PerturbRequest,
    PerturbResponse,
    PredictionDelta,
)
from app.security.limiter import limiter
from app.services.pe_features import FEATURE_SCHEMA_VERSION, FEATURE_VECTOR_ORDER, PEFeatures
from app.services.perturb import (
    Perturbation,
    PerturbValidationError,
    apply_perturbations,
)

router = APIRouter(tags=["perturb"])


def _vector_from_features(features) -> list[float]:  # type: ignore[no-untyped-def]
    """Mirror PEFeatures.to_vector but operating on a Pydantic FeatureResponse.

    Avoids reaching into PEFeatures so the request can come from a client
    that never went through /scan in the same process — e.g. a frontend
    that cached the response from a previous session.
    """
    # Build a fake-PEFeatures-compatible-enough dict so we can reuse the
    # canonical vectorizer. PEFeatures is frozen, so we synthesize a
    # minimal compatible instance via a thin shim.
    pe = PEFeatures(
        schema_version=features.schema_version,
        sha256=features.sha256,
        size_bytes=features.size_bytes,
        machine=features.machine,
        number_of_sections=features.number_of_sections,
        time_date_stamp=features.time_date_stamp,
        characteristics=features.characteristics,
        magic=features.magic,
        major_linker_version=features.major_linker_version,
        minor_linker_version=features.minor_linker_version,
        size_of_code=features.size_of_code,
        size_of_initialized_data=features.size_of_initialized_data,
        size_of_uninitialized_data=features.size_of_uninitialized_data,
        address_of_entry_point=features.address_of_entry_point,
        image_base=features.image_base,
        section_alignment=features.section_alignment,
        file_alignment=features.file_alignment,
        subsystem=features.subsystem,
        dll_characteristics=features.dll_characteristics,
        size_of_image=features.size_of_image,
        size_of_headers=features.size_of_headers,
        imported_dll_count=features.imported_dll_count,
        imported_function_count=features.imported_function_count,
        has_signature=features.has_signature,
        has_resources=features.has_resources,
        has_debug=features.has_debug,
        has_tls=features.has_tls,
        sections=[],  # vectorizer reads aggregates from sections; we have none here
        imported_dlls=[],
    )
    # Section aggregates: the FeatureResponse doesn't carry section bytes,
    # so we have to fall back to whatever the vectorizer would compute on
    # an empty section list. That's fine for perturbation — the user can
    # still set the aggregate features directly via "set" ops.
    return pe.to_vector()


@router.post("/perturb", response_model=PerturbResponse)
@limiter.limit("30/minute")
async def perturb(request: Request, payload: PerturbRequest) -> PerturbResponse:
    if payload.feature_vector is not None:
        vector = list(payload.feature_vector)
        sha256: str | None = None
    elif payload.features is not None:
        vector = _vector_from_features(payload.features)
        sha256 = payload.features.sha256
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="One of `features` or `feature_vector` is required.",
        )

    if len(vector) != len(FEATURE_VECTOR_ORDER):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"feature_vector must have {len(FEATURE_VECTOR_ORDER)} entries.",
        )

    perturbations = [
        Perturbation(feature=p.feature, op=p.op, value=p.value) for p in payload.perturbations
    ]

    try:
        result = apply_perturbations(
            vector,
            perturbations,
            model_name=payload.model_name,
        )
    except PerturbValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    deltas = [
        PredictionDelta(
            model_name=b.model_name,
            baseline_label=b.label,
            perturbed_label=p.label,
            label_flipped=b.label != p.label,
            confidence_delta=round(p.confidence - b.confidence, 4),
        )
        for b, p in zip(result.baseline_predictions, result.perturbed_predictions, strict=True)
    ]

    return PerturbResponse(
        sha256=sha256,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        applied=[
            AppliedPerturbationResponse(
                feature=a.feature, op=a.op, before=a.before, after=a.after
            )
            for a in result.applied
        ],
        baseline_predictions=result.baseline_predictions,
        perturbed_predictions=result.perturbed_predictions,
        deltas=deltas,
    )
