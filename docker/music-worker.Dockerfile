# songmaker-music-worker — minimal arq worker, no torch, no scoring/whisper
FROM python:3.12-slim

# git is build-time only: the server extra below resolves two private
# overnightworks libraries by tag (#1349), never a runtime dependency.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

RUN useradd --create-home --shell /bin/bash songmaker
RUN chown songmaker:songmaker /app
USER songmaker
RUN mkdir -p /home/songmaker/.codex

COPY --chown=songmaker pyproject.toml uv.lock ./
# All resolved versions come from the committed uv.lock. The server extra
# pulls in overnightworks-webauth and overnightworks-agent-providers, both
# private git+https sources (#1349): --no-build cannot apply to this sync
# (a git source has no prebuilt wheel to fetch), and the read-only token
# reaches only this RUN's git config through a BuildKit secret, readable
# (mode=0444) because this stage already runs as the non-root songmaker
# user here.
RUN --mount=type=secret,id=overnightworks_read_token,required=true,mode=0444 \
    GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0=url.https://x-access-token:$(cat /run/secrets/overnightworks_read_token)@github.com/overnightworks/.insteadOf \
    GIT_CONFIG_VALUE_0=https://github.com/overnightworks/ \
    uv sync --frozen --no-dev --no-install-project \
    --extra server --extra image # NOSONAR

COPY --chown=root:root src/ src/
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root scripts/arq_healthcheck.py scripts/
USER root
# The local project adds no resolved dependencies and cannot change locked
# versions.
RUN uv pip install --python .venv/bin/python --no-deps --no-build \
    --editable . # NOSONAR

# The audiofiles volume is shared with the web container and the other
# workers, and Docker seeds an empty named volume from whichever image
# mounts it first — as root when that image lacks the directory. Every
# image that mounts it must carry it, owned by songmaker.
RUN chown root:root /app && chmod 755 /app && \
    chmod -R a-w src alembic.ini scripts && \
    install -d -o songmaker -g songmaker /app/data/audio
USER songmaker

ENTRYPOINT ["/app/.venv/bin/arq"]
