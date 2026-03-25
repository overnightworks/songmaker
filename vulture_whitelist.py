"""Vulture whitelist — suppress false positives for intentionally unused code.

Usage: vulture src/ vulture_whitelist.py
"""

from songmaker_cli.parser import SongMeta  # noqa: F401

# cyclopts meta decorator — called by the framework, not directly
from songmaker_cli.main import _launcher  # noqa: F401

_launcher

# pydantic field_validator — called by pydantic, not directly
SongMeta._coerce_track
cls  # noqa: F821  # pydantic validator classmethod parameter

# pydantic model field — used in server response validation
from acestep_engine.models import TaskSubmitResponse  # noqa: F401

TaskSubmitResponse.code
