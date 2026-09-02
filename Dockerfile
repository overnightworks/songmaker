# Stage 1: Build frontend
FROM node:22-slim AS frontend-builder
WORKDIR /app/frontend

RUN corepack enable && corepack prepare pnpm@10.32.1 --activate

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/.npmrc ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build

# Stage 2: Python backend
FROM python:3.12-slim AS backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install dependencies first (cached unless pyproject.toml/uv.lock change)
COPY pyproject.toml uv.lock ./
RUN mkdir -p src/songmaker_cli && touch src/songmaker_cli/__init__.py && \
    uv sync --frozen --no-dev --extra server --extra mcp --extra claude && \
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
RUN uv sync --frozen --no-dev --extra server --extra mcp --extra claude

COPY --from=frontend-builder /app/frontend/build frontend/build

COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

RUN useradd --create-home --shell /bin/bash songmaker
# Only Claude owns a profile today. #407 adds Grok and Codex profiles with
# their consumer; Compose mounts the Claude binary and credential mirror
# read-only.
RUN install -d -o songmaker -g songmaker /home/songmaker/.claude
# Both are volume mount points. Docker seeds an empty named volume from
# whichever image mounts it first — as root when that image lacks the
# directory, which the app can never chown back under cap_drop: ALL.
RUN mkdir -p /app/data/queue-streams /app/data/audio
RUN chown -R songmaker:songmaker /app
USER songmaker

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD /app/.venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
