# songmaker-acestep-worker — leaf image
FROM songmaker/acestep-base:latest

USER root
RUN install -d -o songmaker -g songmaker /app
USER songmaker
WORKDIR /app

# Wrapper venv at /app/.venv installs only fastapi/uvicorn/redis/huggingface_hub
# from the songmaker root pyproject's `acestep-worker` extra. This venv is
# completely independent from /opt/acestep/.venv (different concerns: HTTP
# wrapper vs ACE-Step model subprocess). The wrapper image stays small.
COPY --chown=songmaker pyproject.toml uv.lock ./
# The lockfile's nvidia-ml-py3==7.352.0 entry has only a hashed source
# distribution. Every other dependency must be an already-built wheel. The
# dependencies are frozen and hash-verified; nvidia-ml-py3 is the sole locked
# source distribution.
RUN uv export --frozen --no-dev --no-emit-project \
    --extra acestep-worker --format requirements.txt -o /tmp/requirements.txt && \
    uv venv .venv && \
    uv --no-config pip install --python .venv/bin/python \
    --require-hashes --only-binary :all: --no-binary nvidia-ml-py3 \
    -r /tmp/requirements.txt # NOSONAR

COPY --chown=songmaker src/acestep_engine/ src/acestep_engine/
COPY --chown=songmaker src/acestep_worker/ src/acestep_worker/
# The local project adds no resolved dependencies and cannot change locked
# versions.
RUN uv pip install --python .venv/bin/python --no-deps --no-build \
    --editable . # NOSONAR

# The audiofiles volume is shared with the web container and the other
# workers, and Docker seeds an empty named volume from whichever image
# mounts it first — as root when that image lacks the directory. Every
# image that mounts it must carry it, owned by songmaker.
RUN mkdir -p /app/data/audio

ENTRYPOINT ["uv", "run", "--no-sync", "--frozen", "--no-build", "python", "-m", "acestep_worker"]
