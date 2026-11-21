"""Audio I/O and mastering utilities for Songmaker."""

from songmaker_audio_engine.audio_io import (
    encode_mp3,
    master_audio,
    read_wav_bytes,
    write_stereo_wav,
)
from songmaker_audio_engine.constants import FALLBACK_SAMPLE_RATE
from songmaker_audio_engine.errors import AudioDecodeError, MasteringError

__all__ = [
    "AudioDecodeError",
    "FALLBACK_SAMPLE_RATE",
    "MasteringError",
    "encode_mp3",
    "master_audio",
    "read_wav_bytes",
    "write_stereo_wav",
]
