"""Vulture whitelist — suppress false positives for intentionally unused code.

Usage: vulture src/ tests/ vulture_whitelist.py
"""

from songmaker_cli.main import player  # noqa: F401
from songmaker_cli.parser import SongMeta  # noqa: F401

player
SongMeta.source_path
