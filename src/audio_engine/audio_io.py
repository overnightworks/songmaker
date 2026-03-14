"""Audio I/O and mastering utilities for Songmaker."""

from __future__ import annotations

import logging
import struct
import subprocess
import wave
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from audio_engine.constants import INT16_MAX, TARGET_SAMPLE_RATE
from audio_engine.mastering import master_mono

log = logging.getLogger(__name__)


def write_wav_file(
    filename: str,
    samples: list[float] | np.ndarray,
    sample_rate: int = TARGET_SAMPLE_RATE,
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
    """Read mono WAV file to float samples."""
    with wave.open(filename, "r") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    if sample_width == 2:
        all_samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / INT16_MAX
    elif sample_width == 1:
        all_samples = (
            np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0
        ) / 128.0
    else:
        return np.array([], dtype=np.float64), sample_rate

    if n_channels > 1:
        all_samples = all_samples[::n_channels]

    return all_samples, sample_rate


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
    wav_path: str,
    mp3_path: str,
    target_lufs: float = -14.0,
    stereo_width: float = 1.2,
    bitrate: str = "320k",
    metadata: dict[str, str] | None = None,
) -> bool:
    """Master WAV to MP3 with professional mastering chain.

    Pipeline: multiband compression -> stereo widening ->
    LUFS normalization -> soft clipping -> MP3 encoding (ffmpeg).
    """
    wav_file = Path(wav_path)
    if not wav_file.exists():
        log.error("Mastering failed: WAV file not found: %s", wav_path)
        return False

    samples, sample_rate = read_wav_file(wav_path)
    if len(samples) == 0:
        log.error("Mastering failed: empty WAV file")
        return False

    log.info(
        "Mastering: multiband -> stereo(%.1fx) -> LUFS(%.1f) -> clip",
        stereo_width, target_lufs,
    )
    mastered_left, mastered_right = master_mono(
        samples,
        target_lufs=target_lufs,
        stereo_width=stereo_width,
        sample_rate=sample_rate,
    )

    wav_p = Path(wav_path)
    mastered_wav = str(wav_p.with_stem(wav_p.stem + "_mastered"))
    _write_stereo_wav(mastered_wav, mastered_left, mastered_right, sample_rate)

    cmd = _build_ffmpeg_cmd(mastered_wav, mp3_path, bitrate, metadata)

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        Path(mastered_wav).unlink(missing_ok=True)
        log.info("Mastered to %s", mp3_path)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        Path(mastered_wav).unlink(missing_ok=True)
        log.error("MP3 encoding failed: %s", exc)
        return False


def _build_ffmpeg_cmd(
    input_path: str,
    output_path: str,
    bitrate: str,
    metadata: dict[str, str] | None,
) -> list[str]:
    """Build the ffmpeg command for MP3 encoding with ID3 tags."""
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-codec:a", "libmp3lame", "-b:a", bitrate,
    ]
    if metadata:
        tag_map = {
            "title": "title", "artist": "artist", "album": "album",
            "track": "track", "genre": "genre", "date": "date",
        }
        for key, ffmpeg_key in tag_map.items():
            if metadata.get(key):
                cmd.extend(["-metadata", f"{ffmpeg_key}={metadata[key]}"])
        if metadata.get("lyrics"):
            cmd.extend(["-metadata", f"lyrics={metadata['lyrics']}"])
    cmd.append(output_path)
    return cmd


_EMPTY_SAMPLES: tuple[NDArray[np.float64], int] = (
    np.array([], dtype=np.float64), 0,
)


def read_wav_bytes(data: bytes) -> tuple[NDArray[np.float64], int]:
    """Read WAV bytes into float samples (mono mixdown).

    Supports PCM int16/int32 (format 1) and IEEE float32 (format 3).
    Python's wave module doesn't handle format 3, so we parse manually.
    """
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return _EMPTY_SAMPLES

    pos = 12
    fmt_data = None
    audio_data = None
    while pos < len(data) - 8:
        chunk_id = data[pos:pos + 4]
        chunk_size = struct.unpack_from("<I", data, pos + 4)[0]
        if chunk_id == b"fmt ":
            fmt_data = data[pos + 8:pos + 8 + chunk_size]
        elif chunk_id == b"data":
            audio_data = data[pos + 8:pos + 8 + chunk_size]
            break
        pos += 8 + chunk_size
        if pos % 2 == 1:
            pos += 1

    if fmt_data is None or audio_data is None:
        return _EMPTY_SAMPLES

    audio_format = struct.unpack_from("<H", fmt_data, 0)[0]
    n_channels = struct.unpack_from("<H", fmt_data, 2)[0]
    framerate = struct.unpack_from("<I", fmt_data, 4)[0]
    sampwidth = struct.unpack_from("<H", fmt_data, 14)[0] // 8

    if audio_format == 3 and sampwidth == 4:
        samples = np.frombuffer(
            audio_data[:len(audio_data) // 4 * 4], dtype=np.float32,
        ).astype(np.float64)
    elif audio_format == 1 and sampwidth == 2:
        samples = np.frombuffer(
            audio_data[:len(audio_data) // 2 * 2], dtype=np.int16,
        ).astype(np.float64) / INT16_MAX
    elif audio_format == 1 and sampwidth == 4:
        samples = np.frombuffer(
            audio_data[:len(audio_data) // 4 * 4], dtype=np.int32,
        ).astype(np.float64) / 2147483648.0
    else:
        return _EMPTY_SAMPLES

    if n_channels == 2:
        samples = (samples[0::2] + samples[1::2]) * 0.5

    return samples, framerate


def _write_stereo_wav(
    filename: str,
    left: NDArray[np.float64],
    right: NDArray[np.float64],
    sample_rate: int,
) -> None:
    """Write stereo WAV file from two float channel arrays."""
    n = min(len(left), len(right))
    left_arr = np.clip(left[:n] * INT16_MAX, -INT16_MAX, INT16_MAX - 1).astype(np.int16)
    right_arr = np.clip(right[:n] * INT16_MAX, -INT16_MAX, INT16_MAX - 1).astype(np.int16)

    interleaved = np.empty(n * 2, dtype=np.int16)
    interleaved[0::2] = left_arr
    interleaved[1::2] = right_arr

    with wave.open(filename, "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(interleaved.tobytes())
