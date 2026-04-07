"""Tests for CLI helper functions."""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from unittest.mock import patch

import numpy as np
import pytest

from songmaker_cli.errors import GenerationError, ValidationError
from songmaker_cli.generate import (
    DecodedAudio,
    _decode_audio,
    _write_output,
)
from songmaker_cli.main import main
from songmaker_cli.parser import AlbumMeta, SongMeta


def test_decode_audio_success(make_stereo_wav_bytes: Callable[..., bytes]) -> None:
    from acestep_engine.models import AceStepResult

    wav_bytes = make_stereo_wav_bytes()
    result = AceStepResult(wav_bytes=wav_bytes, seed=1)
    audio = _decode_audio(result)
    assert audio.sample_rate == 44100
    assert audio.duration > 0


def test_decode_audio_empty() -> None:
    from acestep_engine.models import AceStepResult

    result = AceStepResult(wav_bytes=b"not wav", seed=1)
    with pytest.raises(GenerationError, match="decode failed"):
        _decode_audio(result)


def test_write_output(tmp_path: Path) -> None:
    left = np.sin(np.linspace(0, 2 * np.pi * 440, 44100)) * 0.3
    right = left.copy()
    audio = DecodedAudio(left=left, right=right, sample_rate=44100, duration=1.0)

    mp3_path = tmp_path / "song_v1.mp3"
    wav_path = tmp_path / "song_v1.wav"
    meta = SongMeta(title="Song", prompt="rock", lyrics="hello", album="test")
    album_meta = AlbumMeta(title="Album", artist="Artist")

    _write_output(audio, 42, mp3_path, wav_path, meta, album_meta)

    assert mp3_path.exists()
    assert mp3_path.stat().st_size > 0
    assert wav_path.exists()
    assert wav_path.stat().st_size > 0



def test_write_output_mastering_error(tmp_path: Path) -> None:
    left = np.array([], dtype=np.float64)
    right = left.copy()
    audio = DecodedAudio(left=left, right=right, sample_rate=44100, duration=0.0)

    mp3_path = tmp_path / "song_v1.mp3"
    wav_path = tmp_path / "song_v1.wav"
    meta = SongMeta(title="Song", prompt="rock", lyrics="hello", album="test")
    album_meta = AlbumMeta(title="Album", artist="Artist")

    with pytest.raises(GenerationError, match="empty"):
        _write_output(audio, 42, mp3_path, wav_path, meta, album_meta)


def test_write_output_encode_error(tmp_path: Path) -> None:
    left = np.sin(np.linspace(0, 2 * np.pi * 440, 44100)) * 0.3
    right = left.copy()
    audio = DecodedAudio(left=left, right=right, sample_rate=44100, duration=1.0)

    mp3_path = tmp_path / "song_v1.mp3"
    wav_path = tmp_path / "song_v1.wav"
    meta = SongMeta(title="Song", prompt="rock", lyrics="hello", album="test")
    album_meta = AlbumMeta(title="Album", artist="Artist")

    with patch("shutil.which", return_value=None):
        with pytest.raises(GenerationError, match="ffmpeg not found"):
            _write_output(audio, 42, mp3_path, wav_path, meta, album_meta)


def test_main_error_handling() -> None:
    with (
        patch("songmaker_cli.main._launcher", side_effect=ValidationError("test error")),
        pytest.raises(SystemExit),
    ):
        main()


