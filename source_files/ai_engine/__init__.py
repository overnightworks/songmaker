"""AI-powered instrumental generation engine.

Provides MusicGen text-to-music generation for creating backing tracks
from text prompts like "melodic house, deep bass, 124 BPM, E minor".

Runs in an isolated Python 3.12 venv to avoid dependency conflicts.
"""

from ai_engine.musicgen_renderer import MusicGenRenderer, is_musicgen_available

__all__ = ["MusicGenRenderer", "is_musicgen_available"]
