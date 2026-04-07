# songmaker-scoring-worker — arq worker with scoring + whisper extras
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

RUN useradd --create-home --shell /bin/bash songmaker
RUN chown songmaker:songmaker /app
USER songmaker

COPY --chown=songmaker pyproject.toml uv.lock ./
RUN mkdir -p src/songmaker_cli && touch src/songmaker_cli/__init__.py && \
    uv sync --frozen --no-dev --extra server --extra scoring --extra whisper && \
    rm -rf src/songmaker_cli/__init__.py

ENV HF_HUB_CACHE=/app/.cache/huggingface/hub
RUN --mount=type=secret,id=hf_token,env=HF_TOKEN uv run python -c "\
from faster_whisper import WhisperModel; \
WhisperModel('large-v3', device='cpu', compute_type='int8')"
RUN --mount=type=secret,id=hf_token,env=HF_TOKEN uv run python -c "\
from audiobox_aesthetics.infer import AesPredictor; \
import os; os.environ['CUDA_VISIBLE_DEVICES'] = ''; \
AesPredictor(checkpoint_pth='default')"

COPY --chown=songmaker src/ src/
COPY --chown=songmaker alembic.ini ./
RUN uv sync --frozen --no-dev --extra server --extra scoring --extra whisper

ENTRYPOINT ["uv", "run", "arq"]
