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
RUN mkdir -p src/acestep_worker && touch src/acestep_worker/__init__.py && \
    uv sync --frozen --no-dev --extra acestep-worker && \
    rm -rf src/acestep_worker/__init__.py

COPY --chown=songmaker src/acestep_engine/ src/acestep_engine/
COPY --chown=songmaker src/acestep_worker/ src/acestep_worker/
RUN uv sync --frozen --no-dev --extra acestep-worker

ENTRYPOINT ["uv", "run", "python", "-m", "acestep_worker"]
