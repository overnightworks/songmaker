# songmaker-music-worker — minimal arq worker, no torch, no scoring/whisper
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv
FROM python:3.12.16-slim@sha256:8523d6abeb48ceae0b7240d30c5808fc26cb79c1a635bacdf19cf3baecfbec07

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

WORKDIR /app

RUN useradd --create-home --shell /bin/bash songmaker
RUN chown songmaker:songmaker /app
USER songmaker
RUN mkdir -p /home/songmaker/.codex

COPY --chown=songmaker pyproject.toml uv.lock ./
RUN uv sync --frozen --no-build --no-dev --no-install-project \
    --extra server --extra image # why: All resolved versions come from the committed uv.lock.

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
USER songmaker

ENTRYPOINT ["/app/.venv/bin/arq"]
