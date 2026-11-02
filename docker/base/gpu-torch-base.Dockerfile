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
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv
FROM python:3.14.10-slim@sha256:3cabfd7d7aaf394e6040e79fa1eec6ca1c52b74ed9188650472695d9a9326999

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ffmpeg \
    gcc \
    g++ \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

RUN useradd --create-home --shell /bin/bash songmaker
RUN install -d -o songmaker -g songmaker /opt/acestep

USER songmaker
WORKDIR /opt/acestep

# Pre-create the venv at the path acestep-base will COPY the upstream source
# into. Downstream `uv sync` discovers /opt/acestep/.venv, sees torch already
# installed at the upstream-pinned version, and only installs the delta deps.
ENV UV_HTTP_TIMEOUT=600
RUN uv venv --python "$(command -v python3)" .venv \
    && uv pip install --python .venv/bin/python \
        --only-binary :all: \
        --index-url https://download.pytorch.org/whl/cu128 \
        torch==2.10.0+cu128 \
        torchvision==0.25.0+cu128 \
        torchaudio==2.10.0+cu128

ENV PYTHONUNBUFFERED=1
