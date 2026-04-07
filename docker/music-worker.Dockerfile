# songmaker-music-worker — minimal arq worker, no torch, no scoring/whisper
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

RUN useradd --create-home --shell /bin/bash songmaker
RUN chown songmaker:songmaker /app
USER songmaker

COPY --chown=songmaker pyproject.toml uv.lock ./
RUN mkdir -p src/songmaker_cli && touch src/songmaker_cli/__init__.py && \
    uv sync --frozen --no-dev --extra server && \
    rm -rf src/songmaker_cli/__init__.py

COPY --chown=songmaker src/ src/
COPY --chown=songmaker alembic.ini ./
RUN uv sync --frozen --no-dev --extra server

ENTRYPOINT ["uv", "run", "arq"]
