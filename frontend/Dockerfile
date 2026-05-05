# syntax=docker/dockerfile:1.7
#
# Next.js standalone build for production.
#
# Requires `package-lock.json` — produced by `npm install` on a dev box.
# If the lockfile is missing the build will fall back to `npm install`,
# which means the produced image is non-deterministic. CI should fail
# closed on a missing lockfile; we don't enforce here so a fresh clone
# can still build something runnable.

# --- deps stage -----------------------------------------------------------
FROM node:20-alpine AS deps

WORKDIR /app

# Copy lockfile if present, fall back to package.json. `--mount=type=cache`
# would be the BuildKit pattern but we keep it simple here.
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then \
        npm ci --no-audit --no-fund; \
    else \
        echo "WARN: package-lock.json missing — falling back to npm install" >&2; \
        npm install --no-audit --no-fund; \
    fi

# --- builder stage --------------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app

# Next.js inlines NEXT_PUBLIC_* env vars at build time, so the API base
# URL must be present *here*, not at runtime. Default points at the same
# origin (the Caddy proxy strips /api before forwarding to the backend).
ARG NEXT_PUBLIC_API_BASE=/api
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# --- runtime stage --------------------------------------------------------
FROM node:20-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root runtime user. Matches the API container's UID convention so a
# shared volume (none today) wouldn't fight ownership.
RUN addgroup --system --gid 10001 nextjs \
    && adduser  --system --uid 10001 nextjs

# `output: "standalone"` (set in next.config.mjs) produces a self-contained
# `.next/standalone` folder containing the trace-included node_modules and
# a `server.js` entrypoint. The `static` and `public` dirs are still copied
# from the builder because they aren't traced.
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nextjs /app/public ./public

USER nextjs

EXPOSE 3000

# Healthcheck pings the homepage. Anything that returns 200 means Next.js
# is up; we don't depend on a /api/health route on the frontend.
#
# Use 127.0.0.1 explicitly — alpine's busybox `wget` resolves `localhost`
# to ::1 (IPv6), but Next.js binds to 0.0.0.0 (IPv4 only) per HOSTNAME=0.0.0.0
# in the runtime ENV. The bare `localhost` form returns "Connection refused"
# even when Next is up.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget --quiet --spider --tries=1 http://127.0.0.1:3000/ || exit 1

CMD ["node", "server.js"]
