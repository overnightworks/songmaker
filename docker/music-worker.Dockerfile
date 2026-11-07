# songmaker-music-worker — minimal arq worker, no torch, no scoring/whisper
FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv
FROM python:3.14.10-slim@sha256:3cabfd7d7aaf394e6040e79fa1eec6ca1c52b74ed9188650472695d9a9326999

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

WORKDIR /app

# Uid and gid 1000 own the volumes and the checkpoints bind mount, and Kubernetes' runAsNonRoot
# can verify only a numeric USER.
RUN groupadd --gid 1000 songmaker \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash songmaker
RUN chown songmaker:songmaker /app
USER 1000:1000
RUN mkdir -p /home/songmaker/.codex

COPY --chown=songmaker pyproject.toml uv.lock ./
RUN uv sync --frozen --no-build --no-dev --no-install-project \
    --no-install-package overnightworks-webauth \
    --no-install-package overnightworks-agent-runtime-client \
    --extra server --extra image # why: All resolved versions come from the committed uv.lock; --no-build makes any third-party source distribution fail here, so the two git-sourced libraries wait for the next step.
RUN uv sync --frozen --no-dev --no-install-project \
    --extra server --extra image # why: Builds only what the first step left out, the two first-party libraries from their locked git commits.

COPY --chown=root:root src/ src/
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root scripts/arq_healthcheck.py scripts/
USER root
RUN uv pip install --python .venv/bin/python --no-deps --no-build \
    --editable . # why: The local project adds no resolved dependencies and cannot change locked versions.

# The audiofiles volume is shared with the web container and the other
# workers, and Docker seeds an empty named volume from whichever image
# mounts it first — as root when that image lacks the directory. Every
# image that mounts it must carry it, owned by songmaker.
RUN chown root:root /app && chmod 755 /app && \
    chmod -R a-w src alembic.ini scripts && \
    install -d -o songmaker -g songmaker /app/data/audio
USER 1000:1000

ENTRYPOINT ["/app/.venv/bin/python", "-m", "songmaker_cli.arq_worker"]
