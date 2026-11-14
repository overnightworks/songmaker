# Stage 1: uv binary for the backend stage
FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv

# Stage 2: Build frontend
FROM node:26.13.0-slim@sha256:5adad64f9a1fca2d51972caa65983634c8a774eb300d72b20f7f2a0f60368072 AS frontend-builder
WORKDIR /app/frontend

RUN npm install --global pnpm@12.18.0

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
COPY frontend/patches/ ./patches/
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
# Only the CI Compose overlay turns this on, so E2E can map the shipped bundle back to source.
ARG BUILD_SOURCE_MAPS=false
RUN BUILD_SOURCE_MAPS=$BUILD_SOURCE_MAPS pnpm build

# Stage 3: Python backend
FROM python:3.14.10-slim@sha256:3cabfd7d7aaf394e6040e79fa1eec6ca1c52b74ed9188650472695d9a9326999 AS backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/* /var/log/dpkg.log /var/log/alternatives.log /var/log/fontconfig.log /var/log/apt/* \
        /var/cache/ldconfig/aux-cache /var/cache/fontconfig/*

COPY --from=uv /uv /uvx /usr/local/bin/
# Build-only (an ARG, not an ENV, so a uv run in the container keeps its cache): a uv cache in a
# layer is dead weight that differs between builds.
ARG UV_NO_CACHE=1

WORKDIR /app

# Install dependencies first (cached unless pyproject.toml/uv.lock change). The
# app's user cannot write beside the code, so the bytecode is compiled here:
# without it every start compiles the imports again, about 3 s longer.
# Building the git-sourced libraries leaves lock files in /tmp whose names are random per build.
# Both syncs end by removing uv_cache.json from the project's dist-info and RECORD: it holds the
# install's wall-clock time, uv has no switch to leave it out, and the entrypoint syncs nothing (--no-sync).
COPY pyproject.toml uv.lock ./
RUN mkdir -p src/songmaker_cli && touch src/songmaker_cli/__init__.py && \
    uv sync --frozen --no-dev --compile-bytecode --extra server --extra agent --extra image && \
    rm -rf src/songmaker_cli/__init__.py /tmp/uv-*.lock && \
    for marker in .venv/lib/python*/site-packages/*.dist-info/uv_cache.json; do \
        sed -i '/\.dist-info\/uv_cache\.json,/d' "${marker%/*}/RECORD" && rm "$marker"; done

# Copy source code (only this layer rebuilds on code changes)
COPY src/ src/
COPY alembic.ini ./
# Operational one-off scripts (backfills, migrations) run inside this
# container via `docker compose exec songmaker-web /app/.venv/bin/python
# scripts/<name>.py`. Copied whole rather than as an allowlist: scripts/
# is a few hundred KB of trusted first-party code already in the build
# context, and a hand-picked list would silently miss the next operational
# script someone adds.
COPY scripts/ scripts/
# The editable install leaves src/ uncompiled.
RUN uv sync --frozen --no-dev --extra server --extra agent --extra image && \
    .venv/bin/python -m compileall -q src && \
    for marker in .venv/lib/python*/site-packages/*.dist-info/uv_cache.json; do \
        sed -i '/\.dist-info\/uv_cache\.json,/d' "${marker%/*}/RECORD" && rm "$marker"; done

COPY --from=frontend-builder /app/frontend/build frontend/build

COPY docker/scripts/start_web_server.sh /app/start_web_server.sh
RUN chmod +x /app/start_web_server.sh

# Uid and gid 1000 own the volumes and the checkpoints bind mount, and Kubernetes' runAsNonRoot
# can verify only a numeric USER.
RUN groupadd --gid 1000 songmaker \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash songmaker
# The web consumer owns the mounted CLI profile directories; Compose mounts
# the binaries and credential mirrors read-only.
RUN install -d -o songmaker -g songmaker /home/songmaker/.claude /home/songmaker/.grok /home/songmaker/.codex
# Both are volume mount points and the only paths under /app the web process
# writes. Docker seeds an empty named volume from whichever image mounts it
# first — as root when that image lacks the directory, which the app can never
# chown back under cap_drop: ALL. Code, scripts, the virtual environment and
# the frontend build stay root-owned: the app's user reads them and cannot
# rewrite them.
RUN install -d -o songmaker -g songmaker /app/data/queue-streams /app/data/audio
# After the last RUN so the node and uv layers stay cached across releases.
ARG SONGMAKER_RELEASE
ARG SONGMAKER_COMMIT
ENV SONGMAKER_RELEASE=$SONGMAKER_RELEASE SONGMAKER_COMMIT=$SONGMAKER_COMMIT
USER 1000:1000

EXPOSE 8080

ENTRYPOINT ["/app/start_web_server.sh"]
