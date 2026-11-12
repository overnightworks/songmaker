# songmaker-scoring-worker — arq worker with scoring + whisper extras
FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv
FROM python:3.14.10-slim@sha256:3cabfd7d7aaf394e6040e79fa1eec6ca1c52b74ed9188650472695d9a9326999

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    git \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/* /var/log/dpkg.log /var/log/alternatives.log /var/log/fontconfig.log /var/log/apt/* \
        /var/cache/ldconfig/aux-cache /var/cache/fontconfig/*

COPY --from=uv /uv /uvx /usr/local/bin/
# Build-only (an ARG, not an ENV, so a uv run in the container keeps its cache): a uv cache in a
# layer is dead weight that differs between builds.
ARG UV_NO_CACHE=1

WORKDIR /app

# Uid and gid 1000 own the volumes and the checkpoints bind mount, and Kubernetes' runAsNonRoot
# can verify only a numeric USER.
RUN groupadd --gid 1000 songmaker \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash songmaker
RUN chown songmaker:songmaker /app
USER 1000:1000

COPY --chown=songmaker pyproject.toml uv.lock ./
# Building the git-sourced libraries leaves lock files in /tmp whose names are random per build.
RUN uv sync --frozen --no-dev --no-install-project \
    --extra server --extra scoring --extra whisper \
    && rm -f /tmp/uv-*.lock

ARG MODEL_WARMUP_TIMEOUT_SECONDS=1800
ENV HF_HUB_CACHE=/app/.cache/huggingface/hub \
    MODEL_WARMUP_TIMEOUT_SECONDS=${MODEL_WARMUP_TIMEOUT_SECONDS}
# An hf-xet transfer once stalled after downloading most of Whisper's 3 GB checkpoint;
# use Hugging Face's HTTP path for these bounded build-time downloads.
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
# uv_cache.json in the project's dist-info holds the install's wall-clock time and is listed in RECORD;
# uv has no switch to leave it out, and nothing runs `uv sync` in the image again.
RUN uv pip install --python .venv/bin/python --no-deps --no-build \
    --editable . \
    && for marker in .venv/lib/python*/site-packages/*.dist-info/uv_cache.json; do \
        sed -i '/\.dist-info\/uv_cache\.json,/d' "${marker%/*}/RECORD" && rm "$marker"; done # why: The local project adds no resolved dependencies and cannot change locked versions.

# The audiofiles volume is shared with the web container and the other
# workers, and Docker seeds an empty named volume from whichever image
# mounts it first — as root when that image lacks the directory. Every
# image that mounts it must carry it, owned by songmaker.
USER root
RUN chown root:root /app && chown -R root:root src && chmod 755 /app && \
    chmod -R a-w src alembic.ini scripts && \
    install -d -o songmaker -g songmaker /app/data/audio
USER 1000:1000

ENTRYPOINT ["/app/.venv/bin/python", "-m", "songmaker_cli.arq_worker"]
