"""Audio I/O and mastering utilities for Songmaker."""

from audio_engine.audio_io import (
    master_to_mp3,
    read_wav_bytes,
    write_stereo_wav,
)
from audio_engine.constants import FALLBACK_SAMPLE_RATE
from audio_engine.errors import AudioDecodeError, MasteringError

__all__ = [
    "AudioDecodeError",
    "FALLBACK_SAMPLE_RATE",
    "MasteringError",
    "master_to_mp3",
    "read_wav_bytes",
    "write_stereo_wav",
]
