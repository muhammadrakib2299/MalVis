"""Per-IP rate limiting via slowapi.

We rate limit at the application layer because Cloudflare/Caddy may not be
present in every deployment (local dev, self-hosters). The reverse proxy is
defense in depth, not a substitute.

`get_remote_address` reads `request.client.host`, which is the real client IP
because uvicorn is started with `--proxy-headers --forwarded-allow-ips=*`
(see Dockerfile).
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

_settings = get_settings()

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[_settings.rate_limit_global],
    # `headers_enabled=True` would require every rate-limited route to
    # take a `response: Response` parameter so slowapi can inject the
    # X-RateLimit-* headers — every route in this project returns a
    # Pydantic model, not a Response. Skipping the headers keeps the
    # signatures clean; the 429 itself is the contract clients rely on.
    headers_enabled=False,
)
