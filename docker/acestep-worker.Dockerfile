FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

RUN useradd --create-home --shell /bin/bash songmaker
RUN chown songmaker:songmaker /app
USER songmaker

COPY --chown=songmaker pyproject.toml uv.lock ./
RUN mkdir -p src/acestep_worker && touch src/acestep_worker/__init__.py && \
    uv sync --frozen --no-dev --extra acestep-worker && \
    rm -rf src/acestep_worker/__init__.py

COPY --chown=songmaker src/acestep_engine/ src/acestep_engine/
COPY --chown=songmaker src/acestep_worker/ src/acestep_worker/
RUN uv sync --frozen --no-dev --extra acestep-worker

ENV HF_HUB_DISABLE_XET=1
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["uv", "run", "python", "-m", "acestep_worker"]
