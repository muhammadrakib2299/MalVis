"""MalVis backend entry point.

Wires the FastAPI app together: config, security middleware (CORS, rate
limiting), and the liveness probe. Routers and the model registry are added
in subsequent steps.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import get_settings
from app.routers import meta as meta_router
from app.routers import scan as scan_router
from app.security.limiter import limiter

settings = get_settings()

app = FastAPI(
    title="MalVis API",
    description="Explainable malware detection — predictions and SHAP/LIME explanations for Windows PE files.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
)

# --- Rate limiting --------------------------------------------------------
# Wire the limiter onto app.state so route decorators (`@limiter.limit(...)`)
# can find it, then register the middleware + 429 handler.
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request, exc):  # type: ignore[no-untyped-def]
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded.",
            "limit": str(exc.detail),
        },
    )


# --- CORS -----------------------------------------------------------------
# Explicit allowlist only. No wildcards in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=600,
)


# --- Routers --------------------------------------------------------------
app.include_router(scan_router.router)
app.include_router(meta_router.router)


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
