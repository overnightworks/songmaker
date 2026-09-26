from __future__ import annotations

from typing import Final

MODEL_CONFIG_PATHS: Final[dict[str, str]] = {
    "turbo": "acestep-v15-turbo",
    "sft": "acestep-v15-sft",
    "xl-turbo": "acestep-v15-xl-turbo",
    "xl-sft": "acestep-v15-xl-sft",
    "xl-base": "acestep-v15-xl-base",
}

MODE_NOT_LOADED_DETAIL: Final[str] = "Mode {mode} not loaded; call /load_model first"
