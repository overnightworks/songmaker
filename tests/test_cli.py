"""Tests for CLI helper functions."""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from songmaker_cli.config import validate_path
from songmaker_cli.errors import GenerationError, ValidationError
from songmaker_cli.generate import (
    DecodedAudio,
    GenerationOptions,
    _decode_audio,
    _log_generation_banner,
    _log_result_banner,
    _run_generation,
    _write_output,
    load_album_meta_for_song,
    validate_song_meta,
)
from songmaker_cli.main import main
from songmaker_cli.parser import AlbumMeta, SongMeta


def test_validate_path_exists(tmp_path: Path) -> None:
    f = tmp_path / "test.md"
    f.touch()
    result = validate_path(str(f))
    assert result == f.resolve()


def test_validate_path_not_found() -> None:
    with pytest.raises(ValidationError, match="not found"):
        validate_path("/nonexistent/path.md")


def test_validate_song_meta_no_prompt() -> None:
    meta = SongMeta(prompt="", lyrics="[verse]\nHello")
    with pytest.raises(ValidationError, match="prompt"):
        validate_song_meta(meta)


def test_validate_song_meta_no_lyrics() -> None:
    meta = SongMeta(prompt="rock", lyrics="")
    with pytest.raises(ValidationError, match="Lyrics"):
        validate_song_meta(meta)


def test_validate_song_meta_valid() -> None:
    meta = SongMeta(prompt="rock", lyrics="[verse]\nHello")
    validate_song_meta(meta)


def test_generation_options_ace_overrides_filters_none() -> None:
    opts = GenerationOptions(seed=42, duration=60)
    result = opts.ace_overrides()
    assert result == {"seed": 42, "duration": 60}


def test_generation_options_ace_overrides_empty() -> None:
    opts = GenerationOptions()
    result = opts.ace_overrides()
    assert result == {}


def test_generation_options_excludes_non_ace_fields() -> None:
    opts = GenerationOptions(seed=42, count=3)
    result = opts.ace_overrides()
    assert result == {"seed": 42}
    assert "count" not in result


def test_load_album_meta_with_yaml(tmp_path: Path) -> None:
    album_dir = tmp_path / "my_album"
    lyrics_dir = album_dir / "lyrics"
    lyrics_dir.mkdir(parents=True)

    yaml_path = album_dir / "album.yaml"
    yaml_path.write_text("title: My Album\nartist: TestArtist\nyear: 2025\n")

    md_path = lyrics_dir / "song.md"
    md_path.touch()

    meta = load_album_meta_for_song(md_path)
    assert meta.title == "My Album"
    assert meta.artist == "TestArtist"


def test_load_album_meta_without_yaml(tmp_path: Path) -> None:
    lyrics_dir = tmp_path / "cool_album" / "lyrics"
    lyrics_dir.mkdir(parents=True)
    md_path = lyrics_dir / "song.md"
    md_path.touch()

    meta = load_album_meta_for_song(md_path)
    assert meta.title == "Cool Album"


def test_load_album_meta_via_album_name(tmp_path: Path) -> None:
    album_dir = tmp_path / "albums" / "my_album"
    lyrics_dir = album_dir / "lyrics"
    lyrics_dir.mkdir(parents=True)
    (album_dir / "album.yaml").write_text("title: Found Via Name\nartist: Test\n")

    md_path = lyrics_dir / "song.md"
    md_path.touch()

    meta = load_album_meta_for_song(md_path, album_name="my_album", project_root=tmp_path)
    assert meta.title == "Found Via Name"


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
    with pytest.raises(GenerationError, match="empty"):
        _decode_audio(result)


def test_write_output(tmp_path: Path) -> None:
    from songmaker_cli.config import OutputPaths

    left = np.sin(np.linspace(0, 2 * np.pi * 440, 44100)) * 0.3
    right = left.copy()
    audio = DecodedAudio(left=left, right=right, sample_rate=44100, duration=1.0)

    paths = OutputPaths(
        output_dir=tmp_path,
        base_name="song",
        version=1,
        versioned_name="song_v1",
    )
    meta = SongMeta(title="Song", prompt="rock", lyrics="hello", album="test")
    album_meta = AlbumMeta(title="Album", artist="Artist")

    _write_output(audio, 42, paths, meta, album_meta)

    assert paths.mp3.exists()
    assert paths.mp3.stat().st_size > 0
    assert not paths.raw_wav.exists()


def test_log_generation_banner(caplog: pytest.LogCaptureFixture) -> None:
    from acestep_engine.models import AceStepConfig
    from songmaker_cli.config import OutputPaths

    meta = SongMeta(title="Song", album="test", prompt="rock", lyrics="hello")
    paths = OutputPaths(
        output_dir=Path("/tmp"), base_name="song", version=1, versioned_name="song_v1",
    )
    config = AceStepConfig(prompt="rock", lyrics="hello", bpm=120, duration=60, key="Am")

    with caplog.at_level("INFO"):
        _log_generation_banner(meta, paths, config)
    assert "Song" in caplog.text
    assert "120" in caplog.text


def test_log_result_banner(caplog: pytest.LogCaptureFixture) -> None:
    from songmaker_cli.config import OutputPaths

    paths = OutputPaths(
        output_dir=Path("/tmp"), base_name="song", version=1, versioned_name="song_v1",
    )
    audio = DecodedAudio(
        left=np.array([0.0]), right=np.array([0.0]), sample_rate=44100, duration=5.0,
    )
    with caplog.at_level("INFO"):
        _log_result_banner(paths, audio, 42, 10.0)
    assert "Done" in caplog.text
    assert "42" in caplog.text



def test_run_generation_success() -> None:
    import json
    from http.client import HTTPResponse

    from acestep_engine.client import AceStepClient
    from acestep_engine.models import AceStepConfig

    config = AceStepConfig(prompt="test", lyrics="test")
    client = AceStepClient()

    submit_resp = MagicMock(spec=HTTPResponse)
    submit_resp.status = 200
    submit_resp.read.return_value = json.dumps(
        {"data": {"task_id": "t1", "status": "queued"}, "code": 200},
    ).encode()
    submit_resp.__enter__ = MagicMock(return_value=submit_resp)
    submit_resp.__exit__ = MagicMock(return_value=False)

    result_items = json.dumps([{"file": "/v1/audio?path=test.wav", "seed_value": "7"}])
    poll_resp = MagicMock(spec=HTTPResponse)
    poll_resp.status = 200
    poll_resp.read.return_value = json.dumps(
        {"data": [{"task_id": "t1", "status": 1, "result": result_items}]},
    ).encode()
    poll_resp.__enter__ = MagicMock(return_value=poll_resp)
    poll_resp.__exit__ = MagicMock(return_value=False)

    wav_resp = MagicMock(spec=HTTPResponse)
    wav_resp.status = 200
    wav_resp.read.return_value = b"RIFF" + b"\x00" * 40 + b"extra_data"
    wav_resp.__enter__ = MagicMock(return_value=wav_resp)
    wav_resp.__exit__ = MagicMock(return_value=False)

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = [submit_resp, poll_resp, wav_resp]
        result, elapsed = _run_generation(config, client)

    assert result.seed == 7
    assert elapsed >= 0


def test_run_generation_error() -> None:
    from urllib.error import URLError

    from acestep_engine.client import AceStepClient
    from acestep_engine.models import AceStepConfig

    config = AceStepConfig(prompt="test", lyrics="test")
    client = AceStepClient()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = URLError("Connection refused")
        with pytest.raises(GenerationError, match="Connection refused"):
            _run_generation(config, client)



def test_check_command(tmp_path: Path) -> None:
    from songmaker_cli.main import check as check_cmd

    with patch("songmaker_cli.check.run_check") as mock_run:
        check_cmd(path="/some/file.mp3", source="/some/lyrics.md")

    mock_run.assert_called_once_with(
        "/some/file.mp3", "/some/lyrics.md", project_root=None, whisper_model="large-v3",
    )


def test_write_output_mastering_error(tmp_path: Path) -> None:
    from songmaker_cli.config import OutputPaths

    left = np.array([0.5, -0.5], dtype=np.float64)
    right = left.copy()
    audio = DecodedAudio(left=left, right=right, sample_rate=44100, duration=0.01)

    paths = OutputPaths(
        output_dir=tmp_path, base_name="song", version=1, versioned_name="song_v1",
    )
    meta = SongMeta(title="Song", prompt="rock", lyrics="hello", album="test")
    album_meta = AlbumMeta(title="Album", artist="Artist")

    with patch("shutil.which", return_value=None):
        with pytest.raises(GenerationError, match="ffmpeg not found"):
            _write_output(audio, 42, paths, meta, album_meta)


def test_main_error_handling() -> None:
    with (
        patch("songmaker_cli.main._launcher", side_effect=ValidationError("test error")),
        pytest.raises(SystemExit),
    ):
        main()
