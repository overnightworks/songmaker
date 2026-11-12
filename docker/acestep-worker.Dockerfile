# Stage gpu-torch-base
#
# CUDA-enabled torch base image. Creates the venv at /opt/acestep/.venv and
# installs into it the packages only torch needs (torch, torchvision,
# torchaudio, the nvidia libraries, triton, ...) from the upstream lockfile.
# Downstream `acestep-base` COPYs the upstream source tree on top, then runs
# `uv sync --frozen` against the same lockfile, which sees them already
# installed and only installs the delta (diffusers/transformers/nano-vllm/
# gradio/etc).
#
# The torch layer is the heavy one (~4 GB). Its files and their hashes are a function of the
# fork's lock and the Python minor version, so a torch bump is a bump of the fork's lock. Its
# digest also holds file timestamps, which the release build does not fix.
FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv
FROM python:3.14.10-slim@sha256:3cabfd7d7aaf394e6040e79fa1eec6ca1c52b74ed9188650472695d9a9326999 AS gpu-torch-base

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ffmpeg \
    gcc \
    g++ \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/* /var/log/dpkg.log /var/log/alternatives.log /var/log/fontconfig.log /var/log/apt/* \
        /var/cache/ldconfig/aux-cache /var/cache/fontconfig/*

COPY --from=uv /uv /uvx /usr/local/bin/
# Build-only (an ARG, not an ENV, so a uv run in the container keeps its cache): a uv cache in a
# layer is dead weight that differs between builds.
ARG UV_NO_CACHE=1

# Uid and gid 1000 own the volumes and the checkpoints bind mount, and Kubernetes' runAsNonRoot
# can verify only a numeric USER.
RUN groupadd --gid 1000 songmaker \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash songmaker
RUN install -d -o songmaker -g songmaker /opt/acestep

USER 1000:1000
WORKDIR /opt/acestep

# The venv sits at the path acestep-base will COPY the upstream source into. Its pyvenv.cfg holds
# the python and uv versions, so it is a layer of its own below the torch layer.
ENV UV_HTTP_TIMEOUT=600
RUN uv venv --python "$(command -v python3)" .venv

COPY --chown=songmaker vendor/acestep/pyproject.toml vendor/acestep/uv.lock ./

# The torch layer: the upstream lock's packages that only torch brings. Every other package is
# skipped by name (`uv tree` prunes the torch packages and lists what is still reachable on this
# platform) and arrives with acestep-base's delta sync, so a bump of torch is a bump of the fork's
# lock and a bump of any other package leaves this layer untouched. The guard fails the build on an
# empty skip list.
RUN uv_tree="$(uv tree --frozen --no-dev --prune torch --prune torchvision --prune torchaudio)" \
    && skipped_packages="$(printf '%s\n' "$uv_tree" \
        | sed -n 's/^[^A-Za-z0-9]*\([A-Za-z0-9._-]\{1,\}\) v[0-9].*/--no-install-package \1/p' \
        | sort -u)" \
    && test -n "$skipped_packages" \
    && uv sync --frozen --no-dev --no-build --no-install-project $skipped_packages

ENV PYTHONUNBUFFERED=1

# Stage acestep-base
#
# Adds the upstream ACE-Step source tree at /opt/acestep on top of
# gpu-torch-base. The torch layer from gpu-torch-base is preserved;
# `uv sync --frozen` only installs the delta deps (diffusers, transformers,
# peft, nano-vllm, gradio, etc).
FROM gpu-torch-base AS acestep-base

ARG UV_NO_CACHE=1
USER 1000:1000
WORKDIR /opt/acestep

# Layer 1: manifest — caches independently of source churn. The lockfile is already in place.
COPY --chown=songmaker vendor/acestep/README.md ./

# Layer 2: nano-vllm path-source dep — required for `uv sync` to resolve.
COPY --chown=songmaker vendor/acestep/acestep/third_parts/ ./acestep/third_parts/

# Layer 3: heavy delta install. The torch layer's packages are already present.
RUN uv sync --frozen --no-dev \
    --no-install-project # why: The upstream path dependency requires its locked source build.

# Layer 3b: the venv's torch is the lock's CUDA build. torch imports packages this delta installs,
# so the check follows it; it needs no GPU, and the missing bytecode keeps the layer empty.
RUN lock_torch="$(uv tree --frozen --no-dev --depth 0 --package torch | sed -n 's/^torch v//p')" \
    && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c \
        'import sys, torch; assert torch.__version__ == sys.argv[1], torch.__version__; assert torch.version.cuda, "CPU torch"' \
        "$lock_torch"

# Layer 4: full upstream source. Invalidates only on upstream source edits.
COPY --chown=songmaker vendor/acestep/ ./

# Layer 5: editable install of the upstream project so the `acestep-api`
# entry point exists and `_get_project_root()` resolves to /opt/acestep at
# runtime.
RUN uv sync --frozen --no-dev # why: The copied upstream project requires its locked editable source build.

ENV HF_HUB_DISABLE_XET=1

# songmaker-acestep-worker — leaf image
FROM acestep-base

ARG UV_NO_CACHE=1
USER root
RUN install -d -o songmaker -g songmaker /app
USER 1000:1000
WORKDIR /app

# Wrapper venv at /app/.venv installs only fastapi/uvicorn/redis/huggingface_hub
# from the songmaker root pyproject's `acestep-worker` extra. This venv is
# completely independent from /opt/acestep/.venv (different concerns: HTTP
# wrapper vs ACE-Step model subprocess). The wrapper image stays small.
COPY --chown=songmaker pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project \
    --extra acestep-worker --format requirements.txt -o /tmp/requirements.txt && \
    uv venv .venv && \
    uv --no-config pip install --python .venv/bin/python \
    --require-hashes --only-binary :all: --no-binary nvidia-ml-py3 \
    -r /tmp/requirements.txt # why: The lockfile's nvidia-ml-py3==7.352.0 entry has only a hashed source distribution. Every other dependency must be an already-built wheel. The dependencies are frozen and hash-verified; nvidia-ml-py3 is the sole locked source distribution.

COPY --chown=songmaker src/acestep_engine/ src/acestep_engine/
COPY --chown=songmaker src/acestep_worker/ src/acestep_worker/
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
RUN mkdir -p /app/data/audio

# Takes land in this container-local folder, never on the shared volume: music fetches
# them over the authenticated worker HTTP. The worker empties it at every start.
RUN mkdir -p /app/data/worker_output

ENTRYPOINT ["uv", "run", "--no-sync", "--frozen", "--no-build", "python", "-m", "acestep_worker"]
