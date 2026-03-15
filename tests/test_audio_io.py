"""Tests for audio I/O functions."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from audio_engine.audio_io import (
    build_ffmpeg_cmd,
    master_to_mp3,
    normalize_audio,
    read_wav_bytes,
    read_wav_file,
    sanitize_metadata,
    write_stereo_wav,
    write_wav_file,
)
from audio_engine.errors import MasteringError


def test_write_and_read_wav_roundtrip(tmp_path: Path) -> None:
    original = np.sin(np.linspace(0, 2 * np.pi * 440, 4410, dtype=np.float64)) * 0.5
    wav_path = str(tmp_path / "test.wav")
    write_wav_file(wav_path, original, sample_rate=44100)

    samples, rate = read_wav_file(wav_path)
    assert rate == 44100
    assert len(samples) == len(original)
    assert np.max(np.abs(samples - original)) < 0.001


def test_write_wav_file_clips(tmp_path: Path) -> None:
    hot = np.array([2.0, -2.0, 0.5], dtype=np.float64)
    wav_path = str(tmp_path / "clip.wav")
    write_wav_file(wav_path, hot)

    samples, _ = read_wav_file(wav_path)
    assert float(np.max(np.abs(samples))) <= 1.0


def test_read_wav_file_mono(tmp_path: Path) -> None:
    wav_path = str(tmp_path / "mono.wav")
    with wave.open(wav_path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(np.array([16383, -16383], dtype=np.int16).tobytes())

    samples, rate = read_wav_file(wav_path)
    assert rate == 44100
    assert len(samples) == 2
    assert abs(samples[0] - 0.5) < 0.01


def test_normalize_audio() -> None:
    samples = np.array([0.5, -0.25, 0.1], dtype=np.float64)
    normed = normalize_audio(samples, target_peak=0.95)
    assert abs(float(np.max(np.abs(normed))) - 0.95) < 0.001


def test_normalize_audio_silent() -> None:
    samples = np.array([0.0, 0.0, 0.0], dtype=np.float64)
    normed = normalize_audio(samples)
    assert np.array_equal(normed, samples)


def test_normalize_audio_empty() -> None:
    samples = np.array([], dtype=np.float64)
    normed = normalize_audio(samples)
    assert len(normed) == 0


def test_read_wav_bytes_int16() -> None:
    samples = np.array([16384, -16384, 0], dtype=np.int16)
    data = _make_wav_bytes(samples.tobytes(), n_channels=1, sampwidth=2)
    left, right, rate = read_wav_bytes(data)
    assert rate == 44100
    assert len(left) == 3
    assert abs(left[0] - 0.5) < 0.01
    assert np.array_equal(left, right)


def test_read_wav_bytes_float32() -> None:
    samples = np.array([0.5, -0.5], dtype=np.float32)
    data = _make_wav_bytes(
        samples.tobytes(), n_channels=1, sampwidth=4, audio_format=3,
    )
    left, right, rate = read_wav_bytes(data)
    assert rate == 44100
    assert len(left) == 2
    assert abs(left[0] - 0.5) < 0.001
    assert np.array_equal(left, right)


def test_read_wav_bytes_stereo() -> None:
    left_in = np.array([0.8, 0.4], dtype=np.float32)
    right_in = np.array([0.2, 0.6], dtype=np.float32)
    interleaved = np.empty(4, dtype=np.float32)
    interleaved[0::2] = left_in
    interleaved[1::2] = right_in
    data = _make_wav_bytes(
        interleaved.tobytes(), n_channels=2, sampwidth=4, audio_format=3,
    )
    left, right, rate = read_wav_bytes(data)
    assert rate == 44100
    assert len(left) == 2
    assert abs(left[0] - 0.8) < 0.001
    assert abs(right[0] - 0.2) < 0.001


def test_read_wav_bytes_invalid() -> None:
    left, right, rate = read_wav_bytes(b"not a wav file")
    assert len(left) == 0
    assert len(right) == 0
    assert rate == 0


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
    assert "title=Song" in " ".join(cmd)
    assert "artist=Me" in " ".join(cmd)
    assert "lyrics=Hello" in " ".join(cmd)


def test_sanitize_metadata_strips_newlines() -> None:
    assert sanitize_metadata("Hello\nWorld\r\n") == "Hello World  "


def test_sanitize_metadata_strips_null() -> None:
    assert sanitize_metadata("Hello\x00World") == "Hello World"


def test_sanitize_metadata_passes_normal_text() -> None:
    assert sanitize_metadata('Song "With" Quotes & Stuff') == 'Song "With" Quotes & Stuff'


def test_read_wav_file_stereo_downmix(tmp_path: Path) -> None:
    wav_path = str(tmp_path / "stereo.wav")
    left = np.array([0.5, -0.5], dtype=np.float64)
    right = np.array([0.3, -0.3], dtype=np.float64)
    write_stereo_wav(wav_path, left, right, 44100)

    samples, rate = read_wav_file(wav_path)
    assert rate == 44100
    assert len(samples) == 2


def test_read_wav_bytes_int32() -> None:
    samples = np.array([1073741824, -1073741824], dtype=np.int32)
    data = _make_wav_bytes(samples.tobytes(), n_channels=1, sampwidth=4, audio_format=1)
    left, right, rate = read_wav_bytes(data)
    assert rate == 44100
    assert len(left) == 2
    assert abs(left[0] - 0.5) < 0.01


def test_read_wav_bytes_unsupported_format() -> None:
    data = _make_wav_bytes(b"\x00" * 8, n_channels=1, sampwidth=8, audio_format=99)
    left, right, rate = read_wav_bytes(data)
    assert len(left) == 0
    assert rate == 0


def test_read_wav_bytes_missing_data_chunk() -> None:
    buf = bytearray()
    buf += b"RIFF"
    buf += struct.pack("<I", 20)
    buf += b"WAVE"
    buf += b"fmt "
    fmt_chunk = struct.pack("<HHIIHH", 1, 1, 44100, 88200, 2, 16)
    buf += struct.pack("<I", len(fmt_chunk))
    buf += fmt_chunk
    left, right, rate = read_wav_bytes(bytes(buf))
    assert len(left) == 0


def test_master_to_mp3_empty_audio() -> None:
    empty = np.array([], dtype=np.float64)
    with pytest.raises(MasteringError, match="empty"):
        master_to_mp3(empty, empty, "/tmp/test.mp3")


def test_build_ffmpeg_cmd_pipe_input() -> None:
    cmd = build_ffmpeg_cmd("-", "out.mp3", "320k", None)
    assert "pipe:0" in cmd
    assert "-f" in cmd


def _make_wav_bytes(
    audio_data: bytes,
    n_channels: int = 1,
    sampwidth: int = 2,
    sample_rate: int = 44100,
    audio_format: int = 1,
) -> bytes:
    """Build a minimal WAV byte buffer for testing."""
    fmt_chunk = struct.pack(
        "<HHIIHH",
        audio_format,
        n_channels,
        sample_rate,
        sample_rate * n_channels * sampwidth,
        n_channels * sampwidth,
        sampwidth * 8,
    )
    fmt_size = len(fmt_chunk)
    data_size = len(audio_data)
    riff_size = 4 + (8 + fmt_size) + (8 + data_size)

    buf = bytearray()
    buf += b"RIFF"
    buf += struct.pack("<I", riff_size)
    buf += b"WAVE"
    buf += b"fmt "
    buf += struct.pack("<I", fmt_size)
    buf += fmt_chunk
    buf += b"data"
    buf += struct.pack("<I", data_size)
    buf += audio_data
    return bytes(buf)
