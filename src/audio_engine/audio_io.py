"""Audio I/O and mastering utilities for Songmaker."""

from __future__ import annotations

import logging
import shutil
import struct
import subprocess
import wave

import numpy as np
from numpy.typing import NDArray

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
        log.warning(
            "read_wav_file: %d-channel audio downmixed to mono (left channel only) "
            "— use read_wav_bytes() for stereo",
            n_channels,
        )
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
    cmd = _build_ffmpeg_cmd("-", mp3_path, bitrate, metadata)

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
    import io

    interleaved = _interleave_to_int16(left, right)

    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(interleaved.tobytes())
    return buf.getvalue()


def _sanitize_metadata(value: str) -> str:
    """Strip characters that can break ffmpeg -metadata parsing."""
    return str(value).replace("\n", " ").replace("\r", " ").replace("\x00", "")


def _build_ffmpeg_cmd(
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
        tag_map = {
            "title": "title", "artist": "artist", "album": "album",
            "track": "track", "genre": "genre", "date": "date",
            "comment": "comment",
        }
        for key, ffmpeg_key in tag_map.items():
            if metadata.get(key):
                cmd.extend(["-metadata", f"{ffmpeg_key}={_sanitize_metadata(metadata[key])}"])
        if metadata.get("lyrics"):
            cmd.extend(["-metadata", f"lyrics={_sanitize_metadata(metadata['lyrics'])}"])
    cmd.append(output_path)
    return cmd


def _empty_stereo() -> tuple[NDArray[np.float64], NDArray[np.float64], int]:
    """Return a fresh empty stereo tuple (prevents accidental mutation of shared state)."""
    return np.array([], dtype=np.float64), np.array([], dtype=np.float64), 0


def read_wav_bytes(
    data: bytes,
) -> tuple[NDArray[np.float64], NDArray[np.float64], int]:
    """Read WAV bytes into stereo float samples (L, R, sample_rate).

    Hand-rolls WAV chunk parsing instead of using stdlib wave.open because
    ACE-Step outputs IEEE float32 (audio_format=3) WAV files, which the
    stdlib wave module does not support.

    Supports PCM int16/int32 (format 1) and IEEE float32 (format 3).
    Mono input is duplicated to both channels.
    """
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        log.warning("read_wav_bytes: not a valid WAV file (%d bytes)", len(data))
        return _empty_stereo()

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
        log.warning("read_wav_bytes: missing fmt or data chunk")
        return _empty_stereo()

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
        log.warning(
            "read_wav_bytes: unsupported format (audio_format=%d, sample_width=%d bytes)",
            audio_format, sampwidth,
        )
        return _empty_stereo()

    if n_channels >= 2:
        left = samples[0::n_channels]
        right = samples[1::n_channels]
    else:
        left = samples
        right = samples.copy()

    return left, right, framerate


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
