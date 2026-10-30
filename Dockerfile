# Stage 1: uv binary for the backend stage
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

# Stage 2: Build frontend
FROM node:22.23.4-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS frontend-builder
WORKDIR /app/frontend

RUN corepack enable && corepack prepare pnpm@10.32.1 --activate

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/.npmrc ./
COPY frontend/patches/ ./patches/
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build

# Stage 3: Python backend
FROM python:3.14.10-slim@sha256:3cabfd7d7aaf394e6040e79fa1eec6ca1c52b74ed9188650472695d9a9326999 AS backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    bubblewrap \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

WORKDIR /app

# Install dependencies first (cached unless pyproject.toml/uv.lock change)
COPY pyproject.toml uv.lock ./
RUN mkdir -p src/songmaker_cli && touch src/songmaker_cli/__init__.py && \
    uv sync --frozen --no-dev --extra server --extra mcp --extra agent-service --extra api --extra image && \
    rm -rf src/songmaker_cli/__init__.py

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
RUN uv sync --frozen --no-dev --extra server --extra mcp --extra agent-service --extra api --extra image

COPY --from=frontend-builder /app/frontend/build frontend/build

COPY docker/docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

RUN useradd --create-home --shell /bin/bash songmaker
# The web consumer owns the mounted CLI profile directories; Compose mounts
# the binaries and credential mirrors read-only.
RUN install -d -o songmaker -g songmaker /home/songmaker/.claude /home/songmaker/.grok /home/songmaker/.codex
# Both are volume mount points. Docker seeds an empty named volume from
# whichever image mounts it first — as root when that image lacks the
# directory, which the app can never chown back under cap_drop: ALL.
RUN mkdir -p /app/data/queue-streams /app/data/audio
RUN chown -R songmaker:songmaker /app
# After the last RUN so the node and uv layers stay cached across releases.
ARG SONGMAKER_RELEASE
ARG SONGMAKER_COMMIT
ENV SONGMAKER_RELEASE=$SONGMAKER_RELEASE SONGMAKER_COMMIT=$SONGMAKER_COMMIT
USER songmaker

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD /app/.venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
