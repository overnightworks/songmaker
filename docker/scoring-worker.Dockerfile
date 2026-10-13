# songmaker-scoring-worker — arq worker with scoring + whisper extras
FROM python:3.12-slim

# git resolves two private overnightworks libraries by tag (#1349) in the
# server extra below. This is a single-stage image, so the apt package
# ships in the final image too, even though no runtime code path invokes it.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    libc6-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

RUN useradd --create-home --shell /bin/bash songmaker
RUN chown songmaker:songmaker /app
USER songmaker

COPY --chown=songmaker pyproject.toml uv.lock ./
# The lockfile's nvidia-ml-py3==7.352.0 entry has only a hashed source
# distribution, so this locked sync alone may build it. Every dependency
# remains resolved from uv.lock. The server extra also pulls in
# overnightworks-webauth and overnightworks-agent-providers, both private
# git+https sources (#1349); the read-only token reaches only this RUN's
# git config through a BuildKit secret, readable (mode=0444) because this
# stage already runs as the non-root songmaker user here.
RUN --mount=type=secret,id=overnightworks_read_token,required=true,mode=0444 \
    GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0=url.https://x-access-token:$(cat /run/secrets/overnightworks_read_token)@github.com/overnightworks/.insteadOf \
    GIT_CONFIG_VALUE_0=https://github.com/overnightworks/ \
    uv sync --frozen --no-dev --no-install-project \
    --extra server --extra scoring --extra whisper --extra api # NOSONAR

ARG MODEL_WARMUP_TIMEOUT_SECONDS=1800
ENV HF_HUB_CACHE=/app/.cache/huggingface/hub \
    MODEL_WARMUP_TIMEOUT_SECONDS=${MODEL_WARMUP_TIMEOUT_SECONDS}
# 2026-09-05: hf-xet 1.2.0 stalled after downloading most of Whisper's 3 GB
# checkpoint; use Hugging Face's HTTP path for these bounded build-time downloads.
RUN --mount=type=secret,id=hf_token,env=HF_TOKEN \
    HF_HUB_DISABLE_XET=1 timeout --verbose "${MODEL_WARMUP_TIMEOUT_SECONDS}s" \
    uv run --no-sync --frozen --no-build python -c \
    "from faster_whisper import WhisperModel; \
    WhisperModel('large-v3', device='cpu', compute_type='int8')"
RUN --mount=type=secret,id=hf_token,env=HF_TOKEN \
    HF_HUB_DISABLE_XET=1 timeout --verbose "${MODEL_WARMUP_TIMEOUT_SECONDS}s" \
    uv run --no-sync --frozen --no-build python -c \
    "from audiobox_aesthetics.infer import AesPredictor; import os; \
    os.environ['CUDA_VISIBLE_DEVICES'] = ''; AesPredictor(checkpoint_pth='default')"

COPY --chown=songmaker:songmaker src/ src/
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root scripts/arq_healthcheck.py scripts/
# The local project adds no resolved dependencies and cannot change locked
# versions.
RUN uv pip install --python .venv/bin/python --no-deps --no-build \
    --editable . # NOSONAR

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
