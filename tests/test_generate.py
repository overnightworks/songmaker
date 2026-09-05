"""Behavior tests for generation audio post-processing."""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from unittest.mock import patch

import numpy as np
import pytest
from scipy.io import wavfile as scipy_wavfile

from acestep_engine.models import AceStepConfig, AceStepResult
from audio_engine import MasteringError
from songmaker_cli.api_models import BaseGenerationParams
from songmaker_cli.errors import GenerationError
from songmaker_cli.generate import (
    DecodedAudio,
    _decode_audio,
    _read_source_wav,
    _splice_repaint_raw,
    _write_output,
)
from songmaker_cli.parser import AlbumMeta, SongMeta


def _decoded_audio(
    left: list[float], right: list[float], sample_rate: int = 100,
) -> DecodedAudio:
    return DecodedAudio(
        left=np.array(left, dtype=np.float64),
        right=np.array(right, dtype=np.float64),
        sample_rate=sample_rate,
        duration=len(left) / sample_rate,
    )


def _write_source_wav(
    tmp_path: Path,
    make_wav_bytes: Callable[..., bytes],
    samples: np.ndarray,
    n_channels: int,
) -> Path:
    source_path = tmp_path / "source.wav"
    source_path.write_bytes(
        make_wav_bytes(
            samples.tobytes(), n_channels=n_channels, sample_rate=100,
        ),
    )
    return source_path


def _repaint_config(start: float, end: float) -> AceStepConfig:
    return AceStepConfig(
        prompt="repaint", lyrics="lyrics", repainting_start=start, repainting_end=end,
    )


def _song_meta() -> SongMeta:
    return SongMeta(
        title="Song",
        album="Album",
        prompt="rock",
        lyrics="hello",
        generation_params=BaseGenerationParams(),
    )


def test_decode_audio_reports_invalid_wav_as_generation_failure() -> None:
    result = AceStepResult(wav_bytes=b"not a wav", seed=7)

    with pytest.raises(GenerationError, match="ACE-Step audio decode failed"):
        _decode_audio(result)


def test_decode_audio_reports_stereo_duration(
    make_stereo_wav_bytes: Callable[..., bytes],
) -> None:
    audio = _decode_audio(AceStepResult(wav_bytes=make_stereo_wav_bytes(100, 0.04), seed=7))

    assert audio.sample_rate == 100
    assert audio.duration == pytest.approx(0.04)
    assert len(audio.left) == len(audio.right) == 4


def test_read_source_wav_expands_mono_audio_to_stereo(
    tmp_path: Path, make_wav_bytes: Callable[..., bytes],
) -> None:
    source_path = _write_source_wav(
        tmp_path,
        make_wav_bytes,
        np.array([-16384, 0, 16384], dtype=np.int16),
        n_channels=1,
    )

    source = _read_source_wav(str(source_path))

    assert source.sample_rate == 100
    assert source.duration == pytest.approx(0.03)
    np.testing.assert_allclose(source.left, [-0.5, 0.0, 0.5])
    np.testing.assert_allclose(source.right, source.left)


def test_read_source_wav_preserves_stereo_channels(
    tmp_path: Path, make_wav_bytes: Callable[..., bytes],
) -> None:
    source_path = _write_source_wav(
        tmp_path,
        make_wav_bytes,
        np.array([16384, -8192, -16384, 8192], dtype=np.int16),
        n_channels=2,
    )

    source = _read_source_wav(str(source_path))

    np.testing.assert_allclose(source.left, [0.5, -0.5])
    np.testing.assert_allclose(source.right, [-0.25, 0.25])


def test_splice_repaint_crossfades_each_channel(
    tmp_path: Path, make_wav_bytes: Callable[..., bytes],
) -> None:
    source_path = _write_source_wav(
        tmp_path,
        make_wav_bytes,
        np.array([0, 6553] * 10, dtype=np.int16),
        n_channels=2,
    )
    repainted = _decoded_audio([1.0] * 10, [0.8] * 10)

    spliced = _splice_repaint_raw(repainted, _repaint_config(0.02, 0.08), str(source_path))

    np.testing.assert_allclose(
        spliced.left,
        [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 0.5, 0.0, 0.0, 0.0],
    )
    np.testing.assert_allclose(
        spliced.right,
        [0.2, 0.2, 0.2, 0.5, 0.8, 0.8, 0.5, 0.2, 0.2, 0.2],
        atol=1e-4,
    )


def test_splice_repaint_truncates_to_shorter_audio(
    tmp_path: Path, make_wav_bytes: Callable[..., bytes],
) -> None:
    source_path = _write_source_wav(
        tmp_path,
        make_wav_bytes,
        np.array([0, 0] * 6, dtype=np.int16),
        n_channels=2,
    )
    repainted = _decoded_audio([0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8])

    spliced = _splice_repaint_raw(repainted, _repaint_config(0.0, 1.0), str(source_path))

    assert spliced.duration == pytest.approx(0.04)
    np.testing.assert_allclose(spliced.left, repainted.left)
    np.testing.assert_allclose(spliced.right, repainted.right)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (0.0, 0.04, [1.0, 2 / 3, 1 / 3, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        (0.06, 0.1, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1 / 3, 2 / 3, 1.0]),
    ],
)
def test_splice_repaint_crossfades_at_audio_boundaries(
    tmp_path: Path,
    make_wav_bytes: Callable[..., bytes],
    start: float,
    end: float,
    expected: list[float],
) -> None:
    source_path = _write_source_wav(
        tmp_path,
        make_wav_bytes,
        np.zeros(20, dtype=np.int16),
        n_channels=2,
    )
    repainted = _decoded_audio([1.0] * 10, [1.0] * 10)

    spliced = _splice_repaint_raw(repainted, _repaint_config(start, end), str(source_path))

    np.testing.assert_allclose(spliced.left, expected)
    np.testing.assert_allclose(spliced.right, expected)


def test_write_output_writes_mastered_wav_and_encoded_mp3(tmp_path: Path) -> None:
    audio = _decoded_audio([0.1, -0.2, 0.3], [0.4, -0.5, 0.6])
    mp3_path = tmp_path / "song.mp3"
    wav_path = tmp_path / "song.wav"

    def write_mp3(_left, _right, path, **_kwargs) -> None:
        Path(path).write_bytes(b"encoded mp3")

    with (
        patch("songmaker_cli.generate.master_audio", return_value=(audio.left, audio.right)),
        patch("songmaker_cli.generate.encode_mp3", side_effect=write_mp3),
    ):
        _write_output(audio, 42, mp3_path, wav_path, _song_meta(), AlbumMeta(title="Album"))

    sample_rate, samples = scipy_wavfile.read(wav_path)
    assert sample_rate == 100
    np.testing.assert_array_equal(
        samples,
        np.array([[3276, 13107], [-6553, -16384], [9830, 19660]], dtype=np.int16),
    )
    assert mp3_path.read_bytes() == b"encoded mp3"


def test_write_output_stops_before_creating_files_when_mastering_fails(tmp_path: Path) -> None:
    audio = _decoded_audio([0.1], [0.2])
    mp3_path = tmp_path / "song.mp3"
    wav_path = tmp_path / "song.wav"

    with (
        patch(
            "songmaker_cli.generate.master_audio",
            side_effect=MasteringError("mastering unavailable"),
        ),
        pytest.raises(GenerationError, match="mastering unavailable"),
    ):
        _write_output(audio, 42, mp3_path, wav_path, _song_meta(), AlbumMeta(title="Album"))

    assert not wav_path.exists()
    assert not mp3_path.exists()


def test_write_output_keeps_wav_when_mp3_encoding_fails(tmp_path: Path) -> None:
    audio = _decoded_audio([0.1, -0.2], [0.3, -0.4])
    mp3_path = tmp_path / "song.mp3"
    wav_path = tmp_path / "song.wav"

    with (
        patch("songmaker_cli.generate.master_audio", return_value=(audio.left, audio.right)),
        patch(
            "songmaker_cli.generate.encode_mp3",
            side_effect=MasteringError("encoder unavailable"),
        ),
        pytest.raises(GenerationError, match="encoder unavailable"),
    ):
        _write_output(audio, 42, mp3_path, wav_path, _song_meta(), AlbumMeta(title="Album"))

    assert wav_path.exists()
    assert not mp3_path.exists()
