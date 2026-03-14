"""Tests for audio I/O functions."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import numpy as np

from audio_engine.audio_io import (
    _build_ffmpeg_cmd,
    normalize_audio,
    read_wav_bytes,
    read_wav_file,
    write_wav_file,
)


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
    result, rate = read_wav_bytes(data)
    assert rate == 44100
    assert len(result) == 3
    assert abs(result[0] - 0.5) < 0.01


def test_read_wav_bytes_float32() -> None:
    samples = np.array([0.5, -0.5], dtype=np.float32)
    data = _make_wav_bytes(
        samples.tobytes(), n_channels=1, sampwidth=4, audio_format=3,
    )
    result, rate = read_wav_bytes(data)
    assert rate == 44100
    assert len(result) == 2
    assert abs(result[0] - 0.5) < 0.001


def test_read_wav_bytes_stereo_mixdown() -> None:
    left = np.array([0.8, 0.4], dtype=np.float32)
    right = np.array([0.2, 0.6], dtype=np.float32)
    interleaved = np.empty(4, dtype=np.float32)
    interleaved[0::2] = left
    interleaved[1::2] = right
    data = _make_wav_bytes(
        interleaved.tobytes(), n_channels=2, sampwidth=4, audio_format=3,
    )
    result, rate = read_wav_bytes(data)
    assert rate == 44100
    assert len(result) == 2
    assert abs(result[0] - 0.5) < 0.001
    assert abs(result[1] - 0.5) < 0.001


def test_read_wav_bytes_invalid() -> None:
    result, rate = read_wav_bytes(b"not a wav file")
    assert len(result) == 0
    assert rate == 0


def test_build_ffmpeg_cmd_basic() -> None:
    cmd = _build_ffmpeg_cmd("in.wav", "out.mp3", "320k", None)
    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd
    assert "in.wav" in cmd
    assert "out.mp3" in cmd
    assert "320k" in cmd


def test_build_ffmpeg_cmd_with_metadata() -> None:
    meta = {"title": "Song", "artist": "Me", "lyrics": "Hello"}
    cmd = _build_ffmpeg_cmd("in.wav", "out.mp3", "320k", meta)
    assert "title=Song" in " ".join(cmd)
    assert "artist=Me" in " ".join(cmd)
    assert "lyrics=Hello" in " ".join(cmd)


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
