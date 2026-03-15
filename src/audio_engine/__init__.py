"""Audio I/O and mastering utilities for Songmaker."""

from audio_engine.audio_io import (
    master_to_mp3,
    normalize_audio,
    read_wav_bytes,
    read_wav_file,
    write_stereo_wav,
    write_wav_file,
)
from audio_engine.constants import DEFAULT_SAMPLE_RATE
from audio_engine.errors import MasteringError

__all__ = [
    "DEFAULT_SAMPLE_RATE",
    "MasteringError",
    "master_to_mp3",
    "normalize_audio",
    "read_wav_bytes",
    "read_wav_file",
    "write_stereo_wav",
    "write_wav_file",
]
