"""POST /explain — SHAP-style explanation for a PE upload.

Same upload pipeline as /scan (validate, hash, parse), then dispatched
to `explain.explain_features`. Optional `model_name` form field narrows
the response to a single model — the dashboard's "focus this model" view
uses it so the waterfall doesn't redraw two charts when the user has
expanded one.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from app.schemas.explain import ExplainResponse
from app.security.limiter import limiter
from app.security.upload import read_pe_upload
from app.services.explain import ExplainerError, explain_features
from app.services.pe_features import PEParseError, extract_features

router = APIRouter(tags=["explain"])
log = logging.getLogger(__name__)


@router.post("/explain", response_model=ExplainResponse)
@limiter.limit("10/minute")
async def explain(
    request: Request,
    upload: UploadFile = File(..., description="Windows PE file (MZ-prefixed)."),
    model_name: str | None = Form(default=None, description="Restrict explanation to one model."),
    top_n: int = Form(default=12, ge=1, le=64),
) -> ExplainResponse:
    body = await read_pe_upload(upload)
    try:
        features = extract_features(body)
    except PEParseError as exc:
        log.warning("explain_parse_failed detail=%s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not parse the file as a PE.",
        ) from exc
    finally:
        del body

    try:
        return explain_features(features, model_name=model_name, top_n=top_n)
    except ExplainerError as exc:
        # Unknown model name → 404; everything else is genuinely server-side.
        if str(exc).startswith("unknown model"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        log.exception("explain_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Explanation failed.",
        ) from exc
