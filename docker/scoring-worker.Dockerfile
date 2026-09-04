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
# distribution. Every other dependency must be an already-built wheel.
RUN uv export --frozen --no-dev --no-emit-project --extra server --extra scoring --extra whisper --extra claude --format requirements.txt -o /tmp/requirements.txt && \
    uv venv .venv && \
    uv --no-config pip install --python .venv/bin/python --require-hashes --only-binary :all: --no-binary nvidia-ml-py3 --torch-backend cu121 -r /tmp/requirements.txt

ENV HF_HUB_CACHE=/app/.cache/huggingface/hub
RUN --mount=type=secret,id=hf_token,env=HF_TOKEN uv run --no-sync --frozen --no-build python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cpu', compute_type='int8')"
RUN --mount=type=secret,id=hf_token,env=HF_TOKEN uv run --no-sync --frozen --no-build python -c "from audiobox_aesthetics.infer import AesPredictor; import os; os.environ['CUDA_VISIBLE_DEVICES'] = ''; AesPredictor(checkpoint_pth='default')"

COPY --chown=root:root src/ src/
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root scripts/arq_healthcheck.py scripts/
RUN uv pip install --python .venv/bin/python --no-deps --no-build --editable .

# The judge uses only Claude's CLI fallback; Grok and Codex use HTTP APIs.
RUN install -d /home/songmaker/.claude

# The audiofiles volume is shared with the web container and the other
# workers, and Docker seeds an empty named volume from whichever image
# mounts it first — as root when that image lacks the directory. Every
# image that mounts it must carry it, owned by songmaker.
USER root
RUN chown root:root /app && chmod 755 /app && \
    chmod -R a-w src alembic.ini scripts && \
    install -d -o songmaker -g songmaker /app/data/audio
USER songmaker

ENTRYPOINT ["/app/.venv/bin/arq"]
