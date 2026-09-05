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
# The lockfile's nvidia-ml-py3==7.352.0 entry has only a hashed source
# distribution, so this locked sync alone may build it.
RUN uv sync --frozen --no-dev --no-install-project --extra server --extra scoring --extra whisper --extra claude # NOSONAR nvidia-ml-py3 has no wheel in the lockfile; every dependency remains resolved from uv.lock.

ARG MODEL_WARMUP_TIMEOUT_SECONDS=1800
ENV HF_HUB_CACHE=/app/.cache/huggingface/hub \
    MODEL_WARMUP_TIMEOUT_SECONDS=${MODEL_WARMUP_TIMEOUT_SECONDS}
# 2026-09-05: hf-xet 1.2.0 stalled after downloading most of Whisper's 3 GB
# checkpoint; use Hugging Face's HTTP path for these bounded build-time downloads.
RUN --mount=type=secret,id=hf_token,env=HF_TOKEN HF_HUB_DISABLE_XET=1 timeout --verbose "${MODEL_WARMUP_TIMEOUT_SECONDS}s" uv run --no-sync --frozen --no-build python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cpu', compute_type='int8')"
RUN --mount=type=secret,id=hf_token,env=HF_TOKEN HF_HUB_DISABLE_XET=1 timeout --verbose "${MODEL_WARMUP_TIMEOUT_SECONDS}s" uv run --no-sync --frozen --no-build python -c "from audiobox_aesthetics.infer import AesPredictor; import os; os.environ['CUDA_VISIBLE_DEVICES'] = ''; AesPredictor(checkpoint_pth='default')"

COPY --chown=songmaker:songmaker src/ src/
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root scripts/arq_healthcheck.py scripts/
RUN uv pip install --python .venv/bin/python --no-deps --no-build --editable . # NOSONAR The local project adds no resolved dependencies and cannot change locked versions.

# The judge uses only Claude's CLI fallback; Grok and Codex use HTTP APIs.
RUN install -d /home/songmaker/.claude

# The audiofiles volume is shared with the web container and the other
# workers, and Docker seeds an empty named volume from whichever image
# mounts it first — as root when that image lacks the directory. Every
# image that mounts it must carry it, owned by songmaker.
USER root
RUN chown root:root /app && chown -R root:root src && chmod 755 /app && \
    chmod -R a-w src alembic.ini scripts && \
    install -d -o songmaker -g songmaker /app/data/audio
USER songmaker

ENTRYPOINT ["/app/.venv/bin/arq"]
