"""Shared test fixtures for WAV generation and song markdown creation."""

from __future__ import annotations

import os
import struct
import wave
from http.client import HTTPResponse
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

_TEST_SESSION_SECRET = "a" * 64


@pytest.fixture(autouse=True)
def _set_session_secret():
    """Ensure SESSION_SECRET is set for all tests."""
    old = os.environ.get("SESSION_SECRET")
    os.environ["SESSION_SECRET"] = _TEST_SESSION_SECRET
    from songmaker_cli.auth import reset_session_secret
    reset_session_secret()
    yield
    if old is None:
        os.environ.pop("SESSION_SECRET", None)
    else:
        os.environ["SESSION_SECRET"] = old
    reset_session_secret()


def mock_http_response(data: bytes, status: int = 200) -> MagicMock:
    """Build a mock urllib HTTPResponse for ACE-Step client tests."""
    resp = MagicMock(spec=HTTPResponse)
    resp.status = status
    resp.read.return_value = data
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


@pytest.fixture
def make_wav_bytes():
    """Factory fixture: build a minimal WAV byte buffer for testing."""

    def _make(
        audio_data: bytes,
        n_channels: int = 1,
        sampwidth: int = 2,
        sample_rate: int = 44100,
        audio_format: int = 1,
    ) -> bytes:
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

    return _make


@pytest.fixture
def make_stereo_wav_bytes():
    """Factory fixture: build stereo WAV bytes (int16) for testing."""

    def _make(sample_rate: int = 44100, duration: float = 0.1) -> bytes:
        n = int(sample_rate * duration)
        signal = np.zeros(n, dtype=np.int16)
        interleaved = np.empty(n * 2, dtype=np.int16)
        interleaved[0::2] = signal
        interleaved[1::2] = signal
        buf = BytesIO()
        with wave.open(buf, "w") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(interleaved.tobytes())
        return buf.getvalue()

    return _make


@pytest.fixture
def make_sine_wav_bytes():
    """Factory fixture: build stereo WAV bytes containing a sine wave."""

    def _make(
        frequency: float = 440.0,
        duration: float = 2.0,
        sample_rate: int = 44100,
    ) -> bytes:
        n = int(sample_rate * duration)
        t = np.arange(n, dtype=np.float64)
        signal = 0.3 * np.sin(2.0 * np.pi * frequency * t / sample_rate)
        int16 = np.clip(signal * 32768.0, -32768.0, 32767.0).astype(np.int16)

        interleaved = np.empty(n * 2, dtype=np.int16)
        interleaved[0::2] = int16
        interleaved[1::2] = int16

        buf = BytesIO()
        with wave.open(buf, "w") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(interleaved.tobytes())
        return buf.getvalue()

    return _make


@pytest.fixture
def make_song_md():
    """Factory fixture: create a song markdown file in a lyrics directory."""

    def _make(lyrics_dir: Path, stem: str = "01_test_song") -> Path:
        md = lyrics_dir / f"{stem}.md"
        md.write_text(
            "---\ntitle: Test\nprompt: rock\nlanguage: en\n---\n\n## Lyrics\n\n"
            "[verse]\nHello world\nSecond line\n",
        )
        return md

    return _make
