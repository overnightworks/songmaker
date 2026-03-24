"""Tests for audio I/O functions."""

from __future__ import annotations

import struct
from typing import Callable

import numpy as np
import pytest

from audio_engine.audio_io import (
    build_ffmpeg_cmd,
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
    with pytest.raises(AudioDecodeError):
        read_wav_bytes(bytes(buf))


def test_master_to_mp3_empty_audio() -> None:
    empty = np.array([], dtype=np.float64)
    with pytest.raises(MasteringError, match="empty"):
        master_to_mp3(empty, empty, "/tmp/test.mp3")


def test_build_ffmpeg_cmd_pipe_input() -> None:
    cmd = build_ffmpeg_cmd("-", "out.mp3", "320k", None)
    assert "pipe:0" in cmd
    assert "-f" in cmd


