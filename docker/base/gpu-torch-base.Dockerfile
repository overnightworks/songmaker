# songmaker/gpu-torch-base:latest
#
# CUDA-enabled torch base image. Pre-creates the venv at /opt/acestep/.venv
# with torch 2.10.0+cu128 + torchvision + torchaudio installed from the
# upstream PyTorch index. Downstream `acestep-base` COPYs the upstream source
# tree on top, then runs `uv sync --frozen` against the upstream lockfile —
# which sees the existing venv with torch already installed and only installs
# the delta (diffusers/transformers/nano-vllm/gradio/etc).
#
# This is the heavy layer (~6-7 GB after install). Anything downstream stays
# light so the cache survives unrelated changes.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN useradd --create-home --shell /bin/bash songmaker
RUN install -d -o songmaker -g songmaker /opt/acestep

USER songmaker
WORKDIR /opt/acestep

# Pre-create the venv at the path acestep-base will COPY the upstream source
# into. Downstream `uv sync` discovers /opt/acestep/.venv, sees torch already
# installed at the upstream-pinned version, and only installs the delta deps.
ENV UV_HTTP_TIMEOUT=600
RUN uv venv --python 3.12 .venv \
    && uv pip install --python .venv/bin/python \
        --index-url https://download.pytorch.org/whl/cu128 \
        torch==2.10.0+cu128 \
        torchvision==0.25.0+cu128 \
        torchaudio==2.10.0+cu128

ENV PYTHONUNBUFFERED=1
