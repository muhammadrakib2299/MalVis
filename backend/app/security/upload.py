"""Upload validation primitives.

Every check here exists to keep a hostile PE from ever reaching the parser.
Order matters: cheapest rejections run first.

  1. Content-Length header — bail before reading a byte if the client claims
     too much. Note: a malicious client can lie or omit this, so we re-check
     after streaming.
  2. Streamed size cap — bounded read; if the body exceeds the cap mid-read,
     raise immediately instead of buffering the rest.
  3. Magic-byte sniff — anything not starting with `MZ` is not a PE and
     should not feed `pefile` / `LIEF`.
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile, status

from app.config import get_settings

PE_MAGIC = b"MZ"
_settings = get_settings()


class UploadValidationError(HTTPException):
    """Wrapper so callers can catch upload-specific failures cleanly."""


async def read_pe_upload(upload: UploadFile) -> bytes:
    """Read the upload into memory with size and magic-byte checks.

    Returns the raw bytes if valid. Raises HTTPException otherwise.

    The bytes are held in memory, never written to disk — see SECURITY.md.
    Caller is responsible for not retaining the buffer beyond the request.
    """
    max_bytes = _settings.max_upload_bytes

    declared = upload.size
    if declared is not None and declared > max_bytes:
        raise UploadValidationError(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Upload exceeds {max_bytes} bytes (declared {declared}).",
        )

    chunks: list[bytes] = []
    total = 0
    chunk_size = 64 * 1024
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadValidationError(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Upload exceeds {max_bytes} bytes.",
            )
        chunks.append(chunk)

    body = b"".join(chunks)

    if len(body) < 2 or not body.startswith(PE_MAGIC):
        raise UploadValidationError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File does not look like a Windows PE (missing MZ magic).",
        )

    return body


def assert_pe_magic(data: bytes) -> None:
    """Sync helper for callers that already have bytes in hand."""
    if len(data) < 2 or not data.startswith(PE_MAGIC):
        raise UploadValidationError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File does not look like a Windows PE (missing MZ magic).",
        )
