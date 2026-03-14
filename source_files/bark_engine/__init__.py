"""Audio I/O and mastering utilities for Songmaker.

Provides WAV/MP3 reading, writing, mastering, and audio processing.
Originally part of the Bark vocal engine — now standalone audio tooling.

Public API:
    - master_to_mp3: Master audio to MP3 (multiband compression, LUFS, etc.)
    - normalize_audio: Normalize audio to target level
    - write_wav_file / read_wav_file: WAV file I/O
    - overlay_audio / mix_tracks: Audio mixing utilities
    - apply_fade_out: Fade out effect
    - calculate_vocal_durations: Calculate vocal section durations
    - VocalLanguage: Supported voice languages
    - GeneratedVocal: Result container for generated audio
"""

from bark_engine.audio_io import (
    apply_fade_out,
    calculate_vocal_durations,
    master_to_mp3,
    mix_tracks,
    normalize_audio,
    overlay_audio,
    read_wav_file,
    write_wav_file,
)
from bark_engine.constants import TARGET_SAMPLE_RATE
from bark_engine.models import (
    GeneratedVocal,
    VocalLanguage,
    VocalSection,
    VocalStyle,
)

__all__ = [
    "TARGET_SAMPLE_RATE",
    "GeneratedVocal",
    "VocalLanguage",
    "VocalSection",
    "VocalStyle",
    "apply_fade_out",
    "calculate_vocal_durations",
    "master_to_mp3",
    "mix_tracks",
    "normalize_audio",
    "overlay_audio",
    "read_wav_file",
    "write_wav_file",
]
