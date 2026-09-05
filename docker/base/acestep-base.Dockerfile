# songmaker/acestep-base:latest
#
# Adds the upstream ACE-Step source tree at /opt/acestep on top of
# gpu-torch-base. The pre-installed torch from gpu-torch-base is preserved;
# `uv sync --frozen` only installs the delta deps (diffusers, transformers,
# peft, nano-vllm, gradio, etc).
#
# Verified by HARD checkpoint A.5 in plans/acestep-worker-pool-phase8-subplan.md
# that the delta install does NOT reinstall torch/torchvision/torchaudio/cuda libs.
FROM songmaker/gpu-torch-base:latest

USER songmaker
WORKDIR /opt/acestep

# Layer 1: lockfile + manifest only — caches independently of source churn.
COPY --chown=songmaker vendor/acestep/pyproject.toml vendor/acestep/uv.lock vendor/acestep/README.md ./

# Layer 2: nano-vllm path-source dep — required for `uv sync` to resolve.
COPY --chown=songmaker vendor/acestep/acestep/third_parts/ ./acestep/third_parts/

# Layer 3: heavy delta install. torch already present from gpu-torch-base.
# The upstream path dependency requires its locked source build.
RUN uv sync --frozen --no-dev \
    --no-install-project # NOSONAR

# Layer 4: full upstream source. Invalidates only on upstream source edits.
COPY --chown=songmaker vendor/acestep/ ./

# Layer 5: editable install of the upstream project so the `acestep-api`
# entry point exists and `_get_project_root()` resolves to /opt/acestep at
# runtime.
RUN uv sync --frozen --no-dev # NOSONAR The copied upstream project requires its locked editable source build.

ENV HF_HUB_DISABLE_XET=1
