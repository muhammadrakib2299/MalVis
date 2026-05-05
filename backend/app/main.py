"""MalVis backend entry point.

Exposes the FastAPI app and a liveness probe. Heavier wiring (security middleware,
routers, model registry) is added in subsequent steps.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="MalVis API",
    description="Explainable malware detection — predictions and SHAP/LIME explanations for Windows PE files.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness probe. Returns 200 once the process is up.

    Intentionally cheap — no model loads, no DB hits. Readiness for model
    availability lives on a separate endpoint introduced with the registry.
    """
    return {
        "status": "ok",
        "environment": settings.environment,
        "version": app.version,
    }
