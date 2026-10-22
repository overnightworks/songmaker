"""Vulture whitelist — suppress false positives for intentionally unused code.

Usage: vulture src/ scripts/vulture_whitelist.py
"""

from songmaker_cli.parser import SongMeta  # noqa: F401

# pydantic field_validator — called by pydantic, not directly
_ = SongMeta._coerce_track
_ = cls  # noqa: F821  # pydantic validator classmethod parameter

# pydantic model field — used in server response validation
from acestep_engine.models import TaskSubmitResponse  # noqa: F401

_ = TaskSubmitResponse.code
