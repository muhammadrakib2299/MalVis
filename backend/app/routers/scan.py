"""POST /scan — accept a PE upload, return features (and later, predictions).

Pipeline:
  read_pe_upload   → enforces 10 MB cap + MZ-magic check, returns bytes
  extract_features → parses PE in memory, returns flat feature dict
  ScanResponse     → typed Pydantic envelope returned to the client

Model predictions are stubbed to `[]` until the model registry lands. The
shape of `ScanResponse` is final — frontend work can proceed against it.

Rate limiting: per-IP `rate_limit_scan` (default 10/min) on top of the global
default. slowapi reads the limiter from `app.state.limiter`, which is wired
in `main.py` before this router is mounted.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from app.config import Settings, get_settings
from app.schemas.scan import FeatureResponse, ScanResponse
from app.security.limiter import limiter
from app.security.upload import UploadValidationError, read_pe_upload
from app.services.pe_features import PEParseError, extract_features

router = APIRouter(tags=["scan"])
log = logging.getLogger(__name__)


@router.post("/scan", response_model=ScanResponse)
@limiter.limit("10/minute")
async def scan(
    request: Request,
    upload: UploadFile = File(..., description="Windows PE file (MZ-prefixed)."),
    settings: Settings = Depends(get_settings),
) -> ScanResponse:
    # 1. Validate + read upload (10 MB cap, MZ magic). Raises HTTPException on failure.
    body = await read_pe_upload(upload)

    # 2. Extract features. PEParseError → 400 so the client knows it's their input.
    try:
        features = extract_features(body)
    except PEParseError as exc:
        # Log only the SHA-256, never the bytes themselves (SECURITY.md).
        log.warning("pe_parse_failed sha256=%s detail=%s", _hash_only(body), exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not parse the file as a PE.",
        ) from exc

    # 3. Drop the upload buffer eagerly. The bytes have served their purpose
    # and we explicitly do not retain them anywhere (SECURITY.md, "no
    # persistent disk writes").
    del body

    # 4. Build response. Model predictions are stubbed for now; the field
    # exists so the wire format is stable from day one.
    feature_response = FeatureResponse(**features.to_dict())
    return ScanResponse(
        sha256=features.sha256,
        features=feature_response,
        predictions=[],
    )


def _hash_only(data: bytes) -> str:
    """SHA-256 prefix for logs. Cheap, safe, never the file contents."""
    import hashlib

    return hashlib.sha256(data).hexdigest()[:16]


# Re-export so callers can `except UploadValidationError` if they wrap this.
__all__ = ["router", "UploadValidationError"]
