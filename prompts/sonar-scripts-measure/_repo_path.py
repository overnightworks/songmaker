"""Import helpers for scripts that must use their own checkout."""

from __future__ import annotations

import sys
from pathlib import Path


def prepend_own_checkout_src(script_path: str) -> None:
    own_src = Path(script_path).resolve().parents[1] / "src"
    sys.path.insert(0, str(own_src))
