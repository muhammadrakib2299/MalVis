"""Pydantic schemas for the /scan endpoint.

These are the *wire* contracts. The internal feature dataclass
(`services.pe_features.PEFeatures`) is intentionally separate so that future
backend refactors (e.g. swapping `pefile` for LIEF) don't ripple into the
frontend.

Predictions are not yet wired — the model registry lands in the next step.
For now `predictions` is an empty list, but the field is reserved so the
frontend can be built against the final shape from day one.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    virtual_size: int
    raw_size: int
    entropy: float
    characteristics: int


class FeatureResponse(BaseModel):
    """Flat feature payload returned to the frontend."""

    model_config = ConfigDict(frozen=True)

    schema_version: str
    sha256: str
    size_bytes: int

    machine: int
    number_of_sections: int
    time_date_stamp: int
    characteristics: int

    magic: int
    major_linker_version: int
    minor_linker_version: int
    size_of_code: int
    size_of_initialized_data: int
    size_of_uninitialized_data: int
    address_of_entry_point: int
    image_base: int
    section_alignment: int
    file_alignment: int
    subsystem: int
    dll_characteristics: int
    size_of_image: int
    size_of_headers: int

    imported_dll_count: int
    imported_function_count: int
    has_signature: bool
    has_resources: bool
    has_debug: bool
    has_tls: bool

    sections: list[SectionResponse] = Field(default_factory=list)
    imported_dlls: list[str] = Field(default_factory=list)


class ModelPrediction(BaseModel):
    """Per-model prediction. Reserved for the model-registry step."""

    model_config = ConfigDict(frozen=True)

    model_name: str
    label: str
    confidence: float
    latency_ms: float


class ScanResponse(BaseModel):
    """Top-level /scan response."""

    model_config = ConfigDict(frozen=True)

    sha256: str
    features: FeatureResponse
    predictions: list[ModelPrediction] = Field(default_factory=list)
