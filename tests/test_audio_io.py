"""Tests for audio I/O functions."""

from __future__ import annotations

import struct
import subprocess
from typing import Callable

import numpy as np
import pytest

from audio_engine.audio_io import (
    build_ffmpeg_cmd,
    encode_mp3,
    master_audio,
    master_to_mp3,
    read_wav_bytes,
    sanitize_metadata,
)
from audio_engine.errors import MasteringError


def test_read_wav_bytes_int16(make_wav_bytes: Callable[..., bytes]) -> None:
    samples = np.array([16384, -16384, 0], dtype=np.int16)
    data = make_wav_bytes(samples.tobytes(), n_channels=1, sampwidth=2)
    left, right, rate = read_wav_bytes(data)
    assert rate == 44100
    assert len(left) == 3
    assert abs(left[0] - 0.5) < 0.01
    assert np.array_equal(left, right)


def test_read_wav_bytes_float32(make_wav_bytes: Callable[..., bytes]) -> None:
    samples = np.array([0.5, -0.5], dtype=np.float32)
    data = make_wav_bytes(
        samples.tobytes(), n_channels=1, sampwidth=4, audio_format=3,
    )
    left, right, rate = read_wav_bytes(data)
    assert rate == 44100
    assert len(left) == 2
    assert abs(left[0] - 0.5) < 0.001
    assert np.array_equal(left, right)


def test_read_wav_bytes_stereo(make_wav_bytes: Callable[..., bytes]) -> None:
    left_in = np.array([0.8, 0.4], dtype=np.float32)
    right_in = np.array([0.2, 0.6], dtype=np.float32)
    interleaved = np.empty(4, dtype=np.float32)
    interleaved[0::2] = left_in
    interleaved[1::2] = right_in
    data = make_wav_bytes(
        interleaved.tobytes(), n_channels=2, sampwidth=4, audio_format=3,
    )
    left, right, rate = read_wav_bytes(data)
    assert rate == 44100
    assert len(left) == 2
    assert abs(left[0] - 0.8) < 0.001
    assert abs(right[0] - 0.2) < 0.001


def test_read_wav_bytes_invalid() -> None:
    from audio_engine.errors import AudioDecodeError

    with pytest.raises(AudioDecodeError, match="Not a valid WAV"):
        read_wav_bytes(b"not a wav file")


def test_build_ffmpeg_cmd_basic() -> None:
    cmd = build_ffmpeg_cmd("in.wav", "out.mp3", "320k", None)
    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd
    assert "in.wav" in cmd
    assert "out.mp3" in cmd
    assert "320k" in cmd


def test_build_ffmpeg_cmd_with_metadata() -> None:
    meta = {"title": "Song", "artist": "Me", "lyrics": "Hello"}
    cmd = build_ffmpeg_cmd("in.wav", "out.mp3", "320k", meta)
    joined = " ".join(cmd)
    assert "title=Song" in joined
    assert "artist=Me" in joined
    assert "lyrics=Hello" in joined


def test_sanitize_metadata_strips_newlines() -> None:
    assert sanitize_metadata("Hello\nWorld\r\n") == "Hello World  "


def test_sanitize_metadata_strips_null() -> None:
    assert sanitize_metadata("Hello\x00World") == "Hello World"


def test_sanitize_metadata_passes_normal_text() -> None:
    assert sanitize_metadata('Song "With" Quotes & Stuff') == 'Song "With" Quotes & Stuff'


def test_sanitize_metadata_escapes_equals() -> None:
    assert sanitize_metadata("Rock = Life") == "Rock \\= Life"


def test_sanitize_metadata_escapes_backslash() -> None:
    assert sanitize_metadata("path\\to\\file") == "path\\\\to\\\\file"


def test_read_wav_bytes_int32(make_wav_bytes: Callable[..., bytes]) -> None:
    samples = np.array([1073741824, -1073741824], dtype=np.int32)
    data = make_wav_bytes(samples.tobytes(), n_channels=1, sampwidth=4, audio_format=1)
    left, right, rate = read_wav_bytes(data)
    assert rate == 44100
    assert len(left) == 2
    assert abs(left[0] - 0.5) < 0.01


def test_read_wav_bytes_unsupported_format(make_wav_bytes: Callable[..., bytes]) -> None:
    from audio_engine.errors import AudioDecodeError

    data = make_wav_bytes(b"\x00" * 8, n_channels=1, sampwidth=8, audio_format=99)
    with pytest.raises(AudioDecodeError):
        read_wav_bytes(data)


def test_read_wav_bytes_missing_data_chunk() -> None:
    from audio_engine.errors import AudioDecodeError

    buf = bytearray()
    buf += b"RIFF"
    buf += struct.pack("<I", 20)
    buf += b"WAVE"
    buf += b"fmt "
    fmt_chunk = struct.pack("<HHIIHH", 1, 1, 44100, 88200, 2, 16)
    buf += struct.pack("<I", len(fmt_chunk))
    buf += fmt_chunk
    audio_bytes = bytes(buf)
    with pytest.raises(AudioDecodeError):
        read_wav_bytes(audio_bytes)


def test_master_audio_empty() -> None:
    empty = np.array([], dtype=np.float64)
    with pytest.raises(MasteringError, match="empty"):
        master_audio(empty, empty)


def test_master_audio_returns_arrays() -> None:
    signal = np.sin(np.linspace(0, 100, 44100 * 3)).astype(np.float64) * 0.5
    left, right = master_audio(signal, signal.copy())
    assert len(left) == len(signal)
    assert len(right) == len(signal)


def test_encode_mp3_no_ffmpeg() -> None:
    from unittest.mock import patch

    signal = np.zeros(100, dtype=np.float64)
    other_signal = signal.copy()
    with patch("audio_engine.audio_io.shutil.which", return_value=None):
        with pytest.raises(MasteringError, match="ffmpeg not found"):
            encode_mp3(signal, other_signal, "/tmp/test.mp3")


def test_encode_mp3_ffmpeg_failure() -> None:
    from unittest.mock import patch

    signal = np.zeros(100, dtype=np.float64)

    with (
        patch("audio_engine.audio_io.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr=b"error"),
        ),
    ):
        other_signal = signal.copy()
        with pytest.raises(MasteringError, match="MP3 encoding failed"):
            encode_mp3(signal, other_signal, "/tmp/test.mp3")


def test_master_to_mp3_empty_audio() -> None:
    empty = np.array([], dtype=np.float64)
    with pytest.raises(MasteringError, match="empty"):
        master_to_mp3(empty, empty, "/tmp/test.mp3")


def test_master_to_mp3_ffmpeg_failure() -> None:
    from unittest.mock import patch

    signal = np.sin(np.linspace(0, 100, 44100 * 3)).astype(np.float64) * 0.5

    with (
        patch("audio_engine.audio_io.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr=b"error"),
        ),
    ):
        other_signal = signal.copy()
        with pytest.raises(MasteringError, match="MP3 encoding failed"):
            master_to_mp3(signal, other_signal, "/tmp/test.mp3")


def test_build_ffmpeg_cmd_pipe_input() -> None:
    cmd = build_ffmpeg_cmd("-", "out.mp3", "320k", None)
    assert "pipe:0" in cmd
    assert "-f" in cmd


# ── _normalize_dtype edge cases ────────────────────────────────────


def test_read_wav_bytes_uint8(make_wav_bytes: Callable[..., bytes]) -> None:
    samples = np.array([0, 128, 255], dtype=np.uint8)
    data = make_wav_bytes(samples.tobytes(), n_channels=1, sampwidth=1, audio_format=1)
    left, right, rate = read_wav_bytes(data)
    assert rate == 44100
    assert len(left) == 3
    assert abs(left[0] - (-1.0)) < 0.01
    assert abs(left[1] - 0.0) < 0.01
    assert abs(left[2] - (127.0 / 128.0)) < 0.01
    assert np.array_equal(left, right)


def test_read_wav_bytes_float64(make_wav_bytes: Callable[..., bytes]) -> None:
    from audio_engine.audio_io import _normalize_dtype

    raw = np.array([0.5, -0.5], dtype=np.float64)
    result = _normalize_dtype(raw)
    assert result is not None
    assert result.dtype == np.float64
    assert abs(result[0] - 0.5) < 0.001


def test_normalize_dtype_unsupported() -> None:
    from audio_engine.audio_io import _normalize_dtype

    raw = np.array([1, 2, 3], dtype=np.complex128)
    result = _normalize_dtype(raw)
    assert result is None


def test_normalize_dtype_uint8() -> None:
    from audio_engine.audio_io import _normalize_dtype

    raw = np.array([0, 128, 255], dtype=np.uint8)
    result = _normalize_dtype(raw)
    assert result is not None
    assert abs(result[0] - (-1.0)) < 0.01
    assert abs(result[1] - 0.0) < 0.01


def test_normalize_dtype_float32() -> None:
    from audio_engine.audio_io import _normalize_dtype

    raw = np.array([0.5, -0.5], dtype=np.float32)
    result = _normalize_dtype(raw)
    assert result is not None
    assert result.dtype == np.float64


def test_read_wav_bytes_unsupported_dtype() -> None:
    from unittest.mock import patch

    from audio_engine.audio_io import read_wav_bytes
    from audio_engine.errors import AudioDecodeError

    fake_data = np.array([1, 2, 3], dtype=np.complex128)
    with patch("audio_engine.audio_io.scipy_wavfile.read", return_value=(44100, fake_data)):
        valid_header = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 32
        with pytest.raises(AudioDecodeError, match="Unsupported WAV dtype"):
            read_wav_bytes(valid_header)


def test_read_wav_bytes_2d_single_column() -> None:
    from unittest.mock import patch

    from audio_engine.audio_io import read_wav_bytes

    fake_data = np.array([[0.5], [-0.3], [0.1]], dtype=np.float32)
    with patch("audio_engine.audio_io.scipy_wavfile.read", return_value=(44100, fake_data)):
        valid_header = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 32
        left, right, rate = read_wav_bytes(valid_header)
        assert rate == 44100
        assert len(left) == 3
        assert np.array_equal(left, right)
