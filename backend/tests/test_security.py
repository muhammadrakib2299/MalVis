"""Tests for security middleware and upload validation."""

from __future__ import annotations

import io

import pytest
from fastapi import HTTPException, UploadFile

from app.security.upload import PE_MAGIC, assert_pe_magic, read_pe_upload


def _make_upload(payload: bytes, filename: str = "sample.exe") -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(payload), size=len(payload))


def test_assert_pe_magic_accepts_mz_prefix():
    assert_pe_magic(PE_MAGIC + b"\x90" * 100)


def test_assert_pe_magic_rejects_non_pe():
    with pytest.raises(HTTPException) as excinfo:
        assert_pe_magic(b"PK\x03\x04")  # ZIP magic, not PE
    assert excinfo.value.status_code == 400


def test_assert_pe_magic_rejects_empty():
    with pytest.raises(HTTPException) as excinfo:
        assert_pe_magic(b"")
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_read_pe_upload_accepts_minimal_pe():
    body = PE_MAGIC + b"\x00" * 1024
    upload = _make_upload(body)
    out = await read_pe_upload(upload)
    assert out == body


@pytest.mark.asyncio
async def test_read_pe_upload_rejects_oversize_declared(monkeypatch):
    from app.security import upload as upload_mod

    monkeypatch.setattr(upload_mod._settings, "max_upload_bytes", 16)
    body = PE_MAGIC + b"\x00" * 1024
    upload = _make_upload(body)
    with pytest.raises(HTTPException) as excinfo:
        await read_pe_upload(upload)
    assert excinfo.value.status_code == 413


@pytest.mark.asyncio
async def test_read_pe_upload_rejects_non_pe():
    body = b"<html>not a binary</html>"
    upload = _make_upload(body, filename="not.html")
    with pytest.raises(HTTPException) as excinfo:
        await read_pe_upload(upload)
    assert excinfo.value.status_code == 400
