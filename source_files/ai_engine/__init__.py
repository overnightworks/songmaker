"""AI-powered instrumental generation engine.

Provides MusicGen text-to-music generation for creating backing tracks
from text prompts like "melodic house, deep bass, 124 BPM, E minor".
"""

from ai_engine.musicgen_renderer import MusicGenRenderer, is_musicgen_available

__all__ = ["MusicGenRenderer", "is_musicgen_available"]
