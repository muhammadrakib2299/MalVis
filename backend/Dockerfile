# syntax=docker/dockerfile:1.7

# --- Builder stage --------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# System deps needed only for building wheels (e.g. xgboost, shap)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# --- Runtime stage --------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/usr/local/bin:$PATH

# Minimal runtime libs
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 malvis \
    && useradd  --system --uid 10001 --gid malvis --home /app --shell /sbin/nologin malvis

WORKDIR /app

COPY --from=builder /install /usr/local
COPY --chown=malvis:malvis app ./app

USER malvis

# PORT defaults to 8000 (matches docker-compose / Caddy target). Render and
# similar PaaS providers inject their own PORT — the CMD honours it.
# ROOT_PATH defaults to empty: behind a path-stripping reverse proxy (our
# local Caddy strips /api), set ROOT_PATH=/api so Swagger UI generates the
# right openapi.json URL. On a bare subdomain (Render), leave it unset.
ENV PORT=8000

EXPOSE 8000

# Shell form so ${PORT} / ${ROOT_PATH} expand. `exec` replaces the shell
# with uvicorn so SIGTERM reaches the app cleanly.
#
# ${ROOT_PATH:+--root-path "$ROOT_PATH"} — emit the flag only when ROOT_PATH
# is set and non-empty; otherwise FastAPI assumes it's mounted at /.
#
# --proxy-headers + --forwarded-allow-ips=* lets a reverse proxy
# (Caddy / Cloudflare / Render's edge) terminate TLS while preserving the
# real client IP for rate limiting.
CMD exec uvicorn app.main:app \
        --host 0.0.0.0 \
        --port "${PORT:-8000}" \
        ${ROOT_PATH:+--root-path "$ROOT_PATH"} \
        --proxy-headers \
        --forwarded-allow-ips "*"

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8000')+'/health', timeout=3)" || exit 1
