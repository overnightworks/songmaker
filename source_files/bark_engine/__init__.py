"""Bark-based singing vocal engine for MC Tobbisch Birthday Album.

Package providing AI singing vocal generation using Bark (by Suno),
replacing edge-tts speech synthesis with actual singing voices.

Public API:
    - BarkVocalEngine: Core engine for generating singing vocals
    - VocalSection: Immutable configuration for a vocal section
    - VocalStyle: Enum for vocal processing styles
    - VocalLanguage: Supported voice languages
    - GeneratedVocal: Result container for generated audio

Usage:
    from bark_engine import BarkVocalEngine, VocalSection, VocalStyle

    engine = BarkVocalEngine()
    engine.preload_models()
    vocals = engine.generate_vocals([
        VocalSection(section_id="chorus", text="Happy Birthday!", singing=True),
    ])
    engine.cleanup()
"""

from bark_engine.audio_io import (
    apply_fade_out,
    master_to_mp3,
    mix_tracks,
    normalize_audio,
    overlay_audio,
    read_wav_file,
    write_wav_file,
)
from bark_engine.engine import BarkVocalEngine
from bark_engine.models import (
    GeneratedVocal,
    VocalLanguage,
    VocalSection,
    VocalStyle,
)
from bark_engine.constants import BARK_SAMPLE_RATE, TARGET_SAMPLE_RATE

__all__ = [
    "BarkVocalEngine",
    "VocalSection",
    "VocalStyle",
    "VocalLanguage",
    "GeneratedVocal",
    "BARK_SAMPLE_RATE",
    "TARGET_SAMPLE_RATE",
    "write_wav_file",
    "read_wav_file",
    "normalize_audio",
    "overlay_audio",
    "mix_tracks",
    "apply_fade_out",
    "master_to_mp3",
]
