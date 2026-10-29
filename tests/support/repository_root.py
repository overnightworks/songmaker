"""Where the repository checkout lives."""

from __future__ import annotations

from pathlib import Path
from typing import Final

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
