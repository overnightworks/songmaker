"""Audio I/O and mastering utilities for Songmaker."""

from __future__ import annotations

import io
import logging
import shutil
import struct
import subprocess
import wave

import numpy as np
from numpy.typing import NDArray
from scipy.io import wavfile as scipy_wavfile

from audio_engine.constants import DEFAULT_SAMPLE_RATE, INT16_MAX
from audio_engine.errors import MasteringError
from audio_engine.mastering import master_stereo

log = logging.getLogger(__name__)


def write_wav_file(
    filename: str,
    samples: list[float] | np.ndarray,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> None:
    """Write mono WAV file from float samples in [-1.0, 1.0]."""
    arr = np.asarray(samples, dtype=np.float64)
    int16 = np.clip(arr * INT16_MAX, -INT16_MAX, INT16_MAX - 1).astype(np.int16)

    with wave.open(filename, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(int16.tobytes())


def read_wav_file(filename: str) -> tuple[NDArray[np.float64], int]:
    """Read WAV file to mono float samples.

    Uses scipy.io.wavfile which supports PCM int16/int32 and IEEE float32.
    Multi-channel audio is downmixed to mono (left channel only).
    """
    try:
        sample_rate, raw = scipy_wavfile.read(filename)
    except (ValueError, struct.error) as exc:
        log.warning("read_wav_file: failed to parse %s: %s", filename, exc)
        return np.array([], dtype=np.float64), 0

    samples = _normalize_dtype(raw)
    if samples is None:
        log.warning("read_wav_file: unsupported dtype %s", raw.dtype)
        return np.array([], dtype=np.float64), 0

    if samples.ndim == 2 and samples.shape[1] > 1:
        log.warning(
            "read_wav_file: %d-channel audio downmixed to mono (left channel only) "
            "— use read_wav_bytes() for stereo",
            samples.shape[1],
        )
        samples = samples[:, 0]
    elif samples.ndim == 2:
        samples = samples[:, 0]

    return samples, sample_rate


def normalize_audio(
    samples: NDArray[np.float64], target_peak: float = 0.95,
) -> NDArray[np.float64]:
    """Normalize audio to target peak level."""
    if len(samples) == 0:
        return samples
    peak = float(np.max(np.abs(samples)))
    if peak < 0.001:
        return samples
    return samples * (target_peak / peak)


def master_to_mp3(
    left: NDArray[np.float64],
    right: NDArray[np.float64],
    mp3_path: str,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    target_lufs: float = -14.0,
    stereo_width: float = 1.2,
    bitrate: str = "320k",
    metadata: dict[str, str] | None = None,
) -> None:
    """Master stereo audio to MP3.

    Pipeline: multiband compression -> stereo widening ->
    LUFS normalization -> soft clipping -> MP3 encoding (ffmpeg).

    Raises:
        MasteringError: On empty audio, missing ffmpeg, or encoding failure.
    """
    if len(left) == 0 or len(right) == 0:
        raise MasteringError("Cannot master empty audio")

    if not shutil.which("ffmpeg"):
        raise MasteringError("ffmpeg not found on PATH — install ffmpeg to encode MP3s")

    log.info(
        "Mastering: multiband -> stereo(%.1fx) -> LUFS(%.1f) -> clip",
        stereo_width, target_lufs,
    )
    mastered_left, mastered_right = master_stereo(
        left, right,
        target_lufs=target_lufs,
        stereo_width=stereo_width,
        sample_rate=sample_rate,
    )

    wav_bytes = _stereo_to_wav_bytes(mastered_left, mastered_right, sample_rate)
    cmd = build_ffmpeg_cmd("-", mp3_path, bitrate, metadata)

    try:
        subprocess.run(cmd, input=wav_bytes, check=True, capture_output=True)
        log.info("Mastered to %s", mp3_path)
    except subprocess.CalledProcessError as exc:
        raise MasteringError(f"MP3 encoding failed: {exc}") from exc


def _interleave_to_int16(
    left: NDArray[np.float64],
    right: NDArray[np.float64],
) -> NDArray[np.int16]:
    """Clip and interleave stereo float arrays to int16."""
    n = min(len(left), len(right))
    left_arr = np.clip(left[:n] * INT16_MAX, -INT16_MAX, INT16_MAX - 1).astype(np.int16)
    right_arr = np.clip(right[:n] * INT16_MAX, -INT16_MAX, INT16_MAX - 1).astype(np.int16)

    interleaved = np.empty(n * 2, dtype=np.int16)
    interleaved[0::2] = left_arr
    interleaved[1::2] = right_arr
    return interleaved


def _stereo_to_wav_bytes(
    left: NDArray[np.float64],
    right: NDArray[np.float64],
    sample_rate: int,
) -> bytes:
    """Encode stereo float arrays to WAV bytes in memory."""
    interleaved = _interleave_to_int16(left, right)

    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(interleaved.tobytes())
    return buf.getvalue()


def sanitize_metadata(value: str) -> str:
    """Strip characters that can break ffmpeg -metadata parsing.

    Removes control characters (newlines, null bytes, etc.) that could
    interfere with ffmpeg's key=value metadata argument parsing.
    """
    cleaned = str(value)
    cleaned = "".join(ch if ch.isprintable() or ch == " " else " " for ch in cleaned)
    return cleaned


def build_ffmpeg_cmd(
    input_path: str,
    output_path: str,
    bitrate: str,
    metadata: dict[str, str] | None,
) -> list[str]:
    """Build the ffmpeg command for MP3 encoding with ID3 tags."""
    cmd = ["ffmpeg", "-y"]
    if input_path == "-":
        cmd.extend(["-f", "wav", "-i", "pipe:0"])
    else:
        cmd.extend(["-i", input_path])
    cmd.extend(["-codec:a", "libmp3lame", "-b:a", bitrate])
    if metadata:
        for key in ("title", "artist", "album", "track", "genre", "date", "comment", "lyrics"):
            if metadata.get(key):
                cmd.extend(["-metadata", f"{key}={sanitize_metadata(metadata[key])}"])
    cmd.append(output_path)
    return cmd


def _normalize_dtype(raw: np.ndarray) -> NDArray[np.float64] | None:
    """Convert WAV sample array to float64 in [-1.0, 1.0]. Returns None on unsupported dtype."""
    if raw.dtype == np.int16:
        return raw.astype(np.float64) / INT16_MAX
    if raw.dtype == np.int32:
        return raw.astype(np.float64) / 2147483648.0
    if raw.dtype == np.uint8:
        return (raw.astype(np.float64) - 128.0) / 128.0
    if raw.dtype in (np.float32, np.float64):
        return raw.astype(np.float64)
    return None


def _empty_stereo() -> tuple[NDArray[np.float64], NDArray[np.float64], int]:
    """Return a fresh empty stereo tuple (prevents accidental mutation of shared state)."""
    return np.array([], dtype=np.float64), np.array([], dtype=np.float64), 0


def read_wav_bytes(
    data: bytes,
) -> tuple[NDArray[np.float64], NDArray[np.float64], int]:
    """Read WAV bytes into stereo float samples (L, R, sample_rate).

    Uses scipy.io.wavfile which supports PCM int16/int32 and IEEE float32
    (the format ACE-Step outputs). Mono input is duplicated to both channels.
    """
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        log.warning("read_wav_bytes: not a valid WAV file (%d bytes)", len(data))
        return _empty_stereo()

    try:
        sample_rate, raw = scipy_wavfile.read(io.BytesIO(data))
    except (ValueError, struct.error) as exc:
        log.warning("read_wav_bytes: failed to parse WAV data: %s", exc)
        return _empty_stereo()

    samples = _normalize_dtype(raw)
    if samples is None:
        log.warning("read_wav_bytes: unsupported dtype %s", raw.dtype)
        return _empty_stereo()

    if samples.ndim == 2 and samples.shape[1] >= 2:
        left = samples[:, 0]
        right = samples[:, 1]
    else:
        if samples.ndim == 2:
            samples = samples[:, 0]
        left = samples
        right = samples.copy()

    return left, right, sample_rate


def write_stereo_wav(
    filename: str,
    left: NDArray[np.float64],
    right: NDArray[np.float64],
    sample_rate: int,
) -> None:
    """Write stereo WAV file from two float channel arrays."""
    interleaved = _interleave_to_int16(left, right)

    with wave.open(filename, "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(interleaved.tobytes())
