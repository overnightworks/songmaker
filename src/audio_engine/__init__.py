"""Audio I/O and mastering utilities for Songmaker."""

from audio_engine.audio_io import (
    master_to_mp3,
    normalize_audio,
    read_wav_bytes,
    read_wav_file,
    write_wav_file,
)
from audio_engine.constants import TARGET_SAMPLE_RATE

__all__ = [
    "TARGET_SAMPLE_RATE",
    "master_to_mp3",
    "normalize_audio",
    "read_wav_bytes",
    "read_wav_file",
    "write_wav_file",
]
