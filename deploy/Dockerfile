# syntax=docker/dockerfile:1
# Build context: the repository root (compose.yaml sets `context: ..`).
# Targets: `app` (API + worker: Python 3.12, uv, ffmpeg, admin/dist, spec/) and `caddy`
# (proxy: Caddyfile + admin/dist). Both run as non-root users.

ARG NODE_IMAGE=node:24-bookworm-slim
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG CADDY_IMAGE=caddy:2.10-alpine
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.9

# --- admin web: npm ci + tsc + vite → /src/admin/dist ------------------------------------
FROM ${NODE_IMAGE} AS admin
WORKDIR /src/admin
COPY admin/package.json admin/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY admin/ ./
# src/draft/limits.ts and tests import ../spec (route.schema.json, the sample).
COPY spec/ /src/spec/
RUN npm run build

FROM ${UV_IMAGE} AS uv

# --- app: `lutrinh serve` (default) and `lutrinh worker` ---------------------------------
FROM ${PYTHON_IMAGE} AS app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY server/ ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
COPY spec/ /app/spec/
COPY --from=admin /src/admin/dist /app/admin/dist
# uid/gid 10001 own the data directory; bootstrap.sh chowns the host directory to match.
RUN groupadd --system --gid 10001 lutrinh \
    && useradd --system --uid 10001 --gid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin lutrinh \
    && mkdir -p /var/lib/lutrinh/db /var/lib/lutrinh/media /var/lib/lutrinh/uploads \
       /var/lib/lutrinh/backups /var/lib/lutrinh/tmp \
    && chown -R 10001:10001 /var/lib/lutrinh
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LUTRINH_DATA_DIR=/var/lib/lutrinh \
    LUTRINH_SPEC_DIR=/app/spec \
    LUTRINH_ADMIN_DIST_DIR=/app/admin/dist
USER 10001:10001
EXPOSE 8000
# A fresh data directory gets its subdirectories; migrations are idempotent, so running them
# on start makes `docker compose up -d` after an update enough. The worker waits for this
# service to be healthy.
CMD ["sh", "-c", "cd /var/lib/lutrinh && mkdir -p db media uploads backups tmp && cd /app/server && alembic upgrade head && exec lutrinh serve --host 0.0.0.0 --port 8000"]

# --- caddy: TLS, /admin static, /api + /admin/api → app, media via X-Accel-Redirect ------
FROM ${CADDY_IMAGE} AS caddy
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=admin /src/admin/dist /srv/admin
# The image's caddy binary has cap_net_bind_service, so a non-root user can bind 80/443.
# /data (certificates) and /config are named volumes; they inherit this ownership.
RUN addgroup -S -g 10002 caddy \
    && adduser -S -D -H -u 10002 -G caddy caddy \
    && mkdir -p /data/caddy /config/caddy \
    && chown -R 10002:10002 /data /config
USER 10002:10002
