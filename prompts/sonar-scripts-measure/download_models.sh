#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CHECKPOINTS_DIR="$PROJECT_ROOT/vendor/acestep/checkpoints"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python3"
ENV_FILE="$PROJECT_ROOT/.env"

if [[ -f "$ENV_FILE" ]]; then
    HF_TOKEN=$(grep -E '^HF_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
    export HF_TOKEN
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "ERROR: Python venv not found at $VENV_PYTHON — run 'uv sync' first"
    exit 1
fi

MODELS=(
    "ACE-Step/acestep-v15-sft"
    "ACE-Step/acestep-v15-turbo"
    "ACE-Step/acestep-v15-xl-sft"
    "ACE-Step/acestep-v15-xl-turbo"
    "ACE-Step/acestep-v15-xl-base"
)

for model in "${MODELS[@]}"; do
    local_name="${model#ACE-Step/}"
    dest="$CHECKPOINTS_DIR/$local_name"
    if [[ -d "$dest" && -n "$(ls "$dest"/*.safetensors 2>/dev/null)" ]]; then
        echo "SKIP $local_name (already downloaded)"
        continue
    fi
    echo "Downloading $model -> $dest"
    "$VENV_PYTHON" -c "from huggingface_hub import snapshot_download; snapshot_download('$model', local_dir='$dest')"
done

echo "All models downloaded to $CHECKPOINTS_DIR"
