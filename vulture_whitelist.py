"""Vulture whitelist — suppress false positives for intentionally unused code.

Usage: vulture src/ tests/ vulture_whitelist.py
"""

from songmaker_cli.main import player  # noqa: F401
from songmaker_cli.parser import SongMeta  # noqa: F401

player
SongMeta.source_path

# cyclopts meta decorator — called by the framework, not directly
from songmaker_cli.main import _launcher  # noqa: F401

_launcher

# pydantic field_validator — called by pydantic, not directly
SongMeta._coerce_track
cls  # noqa: F821  # pydantic validator classmethod parameter

# pydantic model field — used in server response validation
from acestep_engine.models import TaskSubmitResponse  # noqa: F401

TaskSubmitResponse.code

# dataclass field — serialized to manifest.json
from songmaker_cli.player import TrackInfo  # noqa: F401

TrackInfo.intended

# Mock setup attributes — used by unittest.mock at runtime
from unittest.mock import MagicMock  # noqa: F401

MagicMock.return_value
MagicMock.side_effect
MagicMock.__enter__
MagicMock.__exit__
