"""Tests for facts read from stored audio files."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from songmaker_cli import audio_files

WavFactory = Callable[..., bytes]


def test_read_audio_duration_reads_a_real_audio_file(
    tmp_path: Path, make_stereo_wav_bytes: WavFactory,
) -> None:
    """925_M1_D1 -- a real file's length is read in seconds."""
    wav_path = tmp_path / "clip.wav"
    wav_path.write_bytes(make_stereo_wav_bytes(duration=0.5))

    assert audio_files.read_audio_duration(wav_path) == pytest.approx(0.5, abs=0.01)


@pytest.mark.parametrize(
    "build_contents",
    [
        pytest.param(lambda _make_wav: b"this is not an audio file", id="unrecognized-file"),
        pytest.param(lambda make_wav: make_wav(duration=0.0), id="zero-length-file"),
    ],
)
def test_read_audio_duration_is_none_for_an_unreadable_file(
    tmp_path: Path,
    make_stereo_wav_bytes: WavFactory,
    build_contents: Callable[[WavFactory], bytes],
) -> None:
    """925_M1_D2 -- an unrecognised file and a zero-length file read as None."""
    unreadable_path = tmp_path / "unreadable.wav"
    unreadable_path.write_bytes(build_contents(make_stereo_wav_bytes))

    assert audio_files.read_audio_duration(unreadable_path) is None
