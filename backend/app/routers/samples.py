"""GET /samples and POST /samples/{id}/scan.

The gallery wires the dashboard to a curated set of synthetic PEs the
public can scan without supplying their own binary. Bytes are built on
demand by `app.services.samples`; nothing is read from disk.

Each scan goes through the *same* pipeline as a user upload: the
extractor, the registry, and the cache. So a sample click warms the
prediction cache, and the resulting `/scan/{sha256}` permalink works
immediately without a second extraction.
"""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.scan import FeatureResponse, ScanResponse
from app.security.limiter import limiter
from app.services.extractor import get_extractor
from app.services.model_registry import get_registry
from app.services.pe_features import PEParseError
from app.services.samples import (
    SampleInfo,
    get_sample_bytes,
    has_sample_id,
    list_samples,
)

router = APIRouter(tags=["samples"])
log = logging.getLogger(__name__)


class SampleSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    description: str
    sha256: str
    size_bytes: int


class SamplesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    samples: list[SampleSummary] = Field(default_factory=list)


def _summary(info: SampleInfo) -> SampleSummary:
    return SampleSummary(
        id=info.id,
        label=info.label,
        description=info.description,
        sha256=info.sha256,
        size_bytes=info.size_bytes,
    )


@router.get("/samples", response_model=SamplesResponse)
def list_gallery_samples() -> SamplesResponse:
    """Public metadata for the gallery."""
    return SamplesResponse(samples=[_summary(s) for s in list_samples()])


@router.post("/samples/{sample_id}/scan", response_model=ScanResponse)
@limiter.limit("30/minute")
async def scan_sample(request: Request, sample_id: str) -> ScanResponse:
    """Run the extract → predict pipeline on a curated sample.

    The same hash/cache/registry path as `/scan` so the cache is warm by
    the time the user navigates to a `/scan/{sha256}` permalink.
    """
    if not has_sample_id(sample_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown sample: {sample_id}",
        )

    body = get_sample_bytes(sample_id)
    sha = hashlib.sha256(body).hexdigest()

    # Reuse the scan router's cache via a late import — avoids a circular
    # import at module load time and keeps scan.py the single owner of the
    # cache instance.
    from app.routers.scan import get_scan_cache  # noqa: PLC0415

    cache = get_scan_cache()
    cached = cache.get(sha)
    if cached is not None:
        return cached

    try:
        features = get_extractor().extract(body)
    except PEParseError as exc:
        # Should not happen for synthetic samples, but if a builder ever
        # produces something pefile rejects this surfaces as 500 — that's
        # an operator bug, not a client problem.
        log.exception("sample_parse_failed sample_id=%s", sample_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Sample failed to parse — operator bug.",
        ) from exc

    predictions = get_registry().predict_all(features)
    response = ScanResponse(
        sha256=features.sha256,
        features=FeatureResponse(**features.to_dict()),
        predictions=predictions,
    )
    cache.set(sha, response)
    return response
