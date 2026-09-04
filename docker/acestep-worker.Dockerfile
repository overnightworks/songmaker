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
RUN uv sync --frozen --no-dev --no-install-project --extra acestep-worker # NOSONAR: uv.lock pins nvidia-ml-py3==7.352.0, which has no wheel and must be built from its source distribution.

COPY --chown=songmaker src/acestep_engine/ src/acestep_engine/
COPY --chown=songmaker src/acestep_worker/ src/acestep_worker/
RUN uv sync --frozen --no-dev --extra acestep-worker # NOSONAR: the local Songmaker project is installed editable and has no wheel; third-party dependencies are frozen in uv.lock.

# The audiofiles volume is shared with the web container and the other
# workers, and Docker seeds an empty named volume from whichever image
# mounts it first — as root when that image lacks the directory. Every
# image that mounts it must carry it, owned by songmaker.
RUN mkdir -p /app/data/audio

ENTRYPOINT ["uv", "run", "python", "-m", "acestep_worker"]
