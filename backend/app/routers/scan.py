"""POST /scan — accept a PE upload, return features and per-model predictions.

Pipeline:
  read_pe_upload   → enforces 10 MB cap + MZ-magic check, returns bytes
  hash check       → if the SHA-256 has been scanned recently, return the
                     cached ScanResponse and skip the rest
  extract_features → parses PE in memory, returns flat feature dict
  registry         → runs every loaded model on the feature vector
  ScanResponse     → typed Pydantic envelope returned to the client

Rate limiting: per-IP `rate_limit_scan` (default 10/min) on top of the global
default. slowapi reads the limiter from `app.state.limiter`, which is wired
in `main.py` before this router is mounted.
"""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Path, Request, UploadFile, status

from app.config import Settings, get_settings
from app.schemas.scan import FeatureResponse, ScanResponse
from app.security.limiter import limiter
from app.security.upload import UploadValidationError, read_pe_upload
from app.services.cache import TTLCache
from app.services.extractor import get_extractor
from app.services.model_registry import get_registry
from app.services.pe_features import PEParseError
from app.services.samples import get_sample_by_hash, get_sample_bytes

router = APIRouter(tags=["scan"])
log = logging.getLogger(__name__)


def _build_cache() -> TTLCache[ScanResponse]:
    s = get_settings()
    return TTLCache[ScanResponse](
        max_entries=s.hash_cache_max_entries,
        ttl_seconds=s.hash_cache_ttl_seconds,
    )


# Module-level cache. A singleton is fine — the cache's bounded LRU plus TTL
# means it cannot grow unbounded and stale entries can't outlive the model
# upgrade window.
_cache: TTLCache[ScanResponse] = _build_cache()


def get_scan_cache() -> TTLCache[ScanResponse]:
    """Exposed so tests can clear/inspect the cache without import gymnastics."""
    return _cache


@router.post("/scan", response_model=ScanResponse)
@limiter.limit("10/minute")
async def scan(
    request: Request,
    upload: UploadFile = File(..., description="Windows PE file (MZ-prefixed)."),
    settings: Settings = Depends(get_settings),
) -> ScanResponse:
    # 1. Validate + read upload (10 MB cap, MZ magic). Raises HTTPException on failure.
    body = await read_pe_upload(upload)

    # 2. Cheapest fast path: SHA-256 of the validated bytes. If we've scanned
    # this file recently, the cached prediction is correct by definition (the
    # feature schema and model set are pinned for the cache TTL window).
    sha = hashlib.sha256(body).hexdigest()
    cached = _cache.get(sha)
    if cached is not None:
        del body
        return cached

    # 3. Extract features via the configured extractor (in-process by default,
    # subprocess in hardened deployments). PEParseError → 400.
    try:
        features = get_extractor().extract(body)
    except PEParseError as exc:
        log.warning("pe_parse_failed sha256=%s detail=%s", sha[:16], exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not parse the file as a PE.",
        ) from exc

    # 4. Drop the upload buffer eagerly (SECURITY.md, "no persistent disk writes").
    del body

    # 5. Run every registered model.
    predictions = get_registry().predict_all(features)

    response = ScanResponse(
        sha256=features.sha256,
        features=FeatureResponse(**features.to_dict()),
        predictions=predictions,
    )

    # 6. Cache the response by SHA-256. Bounded LRU + TTL.
    _cache.set(sha, response)
    return response


@router.get("/scan/{sha256}", response_model=ScanResponse)
@limiter.limit("60/minute")
async def lookup_scan(
    request: Request,
    sha256: str = Path(..., pattern=r"^[0-9a-fA-F]{64}$"),
) -> ScanResponse:
    """Permalink lookup for a previously-scanned file.

    Order:
      1. Cache hit → return immediately.
      2. Sample fallback — if `sha256` is one of the curated gallery
         samples, rebuild bytes deterministically and run the pipeline.
         Sample permalinks are *permanent* by construction: the bytes can
         always be reconstructed, so the cache eviction window doesn't
         end the share-ability of a sample link.
      3. 404 — otherwise. We deliberately never store user-uploaded scan
         results past the cache TTL (SECURITY.md), so a permalink for an
         arbitrary upload only works while the prediction is still cached.
    """
    sha = sha256.lower()

    cached = _cache.get(sha)
    if cached is not None:
        return cached

    sample = get_sample_by_hash(sha)
    if sample is not None:
        body = get_sample_bytes(sample.id)
        try:
            features = get_extractor().extract(body)
        except PEParseError as exc:
            log.exception("sample_lookup_parse_failed sample_id=%s", sample.id)
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
        _cache.set(sha, response)
        return response

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No scan with that SHA-256 is available. Uploads are not retained past the cache TTL.",
    )


# Re-export so callers can `except UploadValidationError` if they wrap this.
__all__ = ["router", "UploadValidationError", "get_scan_cache"]
