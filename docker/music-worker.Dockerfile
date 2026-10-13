# songmaker-music-worker — minimal arq worker, no torch, no scoring/whisper
FROM python:3.12-slim

# git resolves two private overnightworks libraries by tag (#1349) in the
# server extra below. This is a single-stage image, so the apt package
# ships in the final image too, even though no runtime code path invokes it.
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
# All resolved versions come from the committed uv.lock, and --no-build
# keeps every third-party dependency wheel-only (docs/security.md). The
# server extra's two private git+https sources (#1349),
# overnightworks-webauth and overnightworks-agent-providers, are the one
# named exception: a git source has no prebuilt wheel to fetch, so each is
# built once from its pinned tag into a local wheel here, excluded from the
# --no-build sync below by name, then installed from that local wheel only
# — never from a bare, unscoped source build. The read-only token reaches
# only this RUN's git config through a BuildKit secret, readable
# (mode=0444) because this stage already runs as the non-root songmaker
# user here.
RUN --mount=type=secret,id=overnightworks_read_token,required=true,mode=0444 \
    export GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0=url.https://x-access-token:$(cat /run/secrets/overnightworks_read_token)@github.com/overnightworks/.insteadOf \
    GIT_CONFIG_VALUE_0=https://github.com/overnightworks/ && \
    mkdir -p /tmp/overnightworks-src /tmp/overnightworks-wheels && \
    git clone --quiet --depth 1 --branch v0.11.0 \
        https://github.com/overnightworks/webauth.git \
        /tmp/overnightworks-src/webauth && \
    git clone --quiet --depth 1 --branch v0.1.2 \
        https://github.com/overnightworks/agent-providers.git \
        /tmp/overnightworks-src/agent-providers && \
    uv build --wheel -o /tmp/overnightworks-wheels /tmp/overnightworks-src/webauth && \
    uv build --wheel -o /tmp/overnightworks-wheels /tmp/overnightworks-src/agent-providers && \
    rm -rf /tmp/overnightworks-src && \
    uv sync --frozen --no-dev --no-build --no-install-project \
        --no-install-package overnightworks-webauth \
        --no-install-package overnightworks-agent-providers \
        --extra server --extra image && \
    uv pip install --python .venv/bin/python --no-deps \
        /tmp/overnightworks-wheels/overnightworks_webauth-*.whl \
        /tmp/overnightworks-wheels/overnightworks_agent_providers-*.whl && \
    rm -rf /tmp/overnightworks-wheels # NOSONAR

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
