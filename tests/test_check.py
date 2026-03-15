"""Tests for the lyrics checking module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from songmaker_cli.check import (
    _log_check_results,
    clean_lyrics,
    find_lyrics_source,
    run_check,
)
from songmaker_cli.errors import ValidationError


def _make_song_md(lyrics_dir: Path, stem: str = "01_test_song") -> Path:
    md = lyrics_dir / f"{stem}.md"
    md.write_text(
        "---\ntitle: Test\nprompt: rock\nlanguage: en\n---\n\n## Lyrics\n\n"
        "[verse]\nHello world\nSecond line\n",
    )
    return md


def test_clean_lyrics_strips_tags() -> None:
    assert clean_lyrics("[verse]\nHello\n[chorus]\nWorld") == "hello world"


def test_clean_lyrics_normalizes_whitespace() -> None:
    assert clean_lyrics("  Hello   World  ") == "hello world"


def test_find_lyrics_source_explicit(tmp_path: Path) -> None:
    md = tmp_path / "song.md"
    md.write_text("---\nprompt: test\n---\n\n## Lyrics\n\nHello\n")
    mp3 = tmp_path / "song_v1.mp3"
    mp3.touch()
    assert find_lyrics_source(mp3, str(md)) == md.resolve()


def test_find_lyrics_source_auto_discovery(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output" / "test_album"
    output_dir.mkdir(parents=True)
    mp3 = output_dir / "01_test_song_v1.mp3"
    mp3.touch()

    albums_dir = tmp_path / "albums" / "test_album" / "lyrics"
    albums_dir.mkdir(parents=True)
    _make_song_md(albums_dir)

    result = find_lyrics_source(mp3, None)
    assert result.name == "01_test_song.md"


def test_find_lyrics_source_not_found(tmp_path: Path) -> None:
    mp3 = tmp_path / "song_v1.mp3"
    mp3.touch()
    with pytest.raises(ValidationError, match="Could not find"):
        find_lyrics_source(mp3, None)


def test_log_check_results_good(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    mp3 = tmp_path / "song.mp3"
    md = tmp_path / "song.md"
    with caplog.at_level("INFO"):
        _log_check_results(mp3, md, 0.9, ["Hello"], ["Hello"], 0.8, 0.5)
    assert "Good" in caplog.text


def test_log_check_results_fair(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    mp3 = tmp_path / "song.mp3"
    md = tmp_path / "song.md"
    with caplog.at_level("INFO"):
        _log_check_results(mp3, md, 0.6, ["Hello"], ["Hola"], 0.8, 0.5)
    assert "Needs improvement" in caplog.text


def test_log_check_results_poor(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    mp3 = tmp_path / "song.mp3"
    md = tmp_path / "song.md"
    with caplog.at_level("INFO"):
        _log_check_results(mp3, md, 0.2, ["Hello"], ["???"], 0.8, 0.5)
    assert "Poor" in caplog.text


def test_run_check_end_to_end(tmp_path: Path) -> None:
    lyrics_dir = tmp_path / "albums" / "test_album" / "lyrics"
    lyrics_dir.mkdir(parents=True)
    md = _make_song_md(lyrics_dir)

    output_dir = tmp_path / "_output" / "test_album"
    output_dir.mkdir(parents=True)
    mp3 = output_dir / "01_test_song_v1.mp3"
    mp3.touch()

    mock_whisper = MagicMock()
    mock_model = MagicMock()
    mock_whisper.load_model.return_value = mock_model
    mock_model.transcribe.return_value = {
        "text": "Hello world second line",
        "segments": [{"text": "Hello world"}, {"text": "second line"}],
    }

    with patch.dict("sys.modules", {"whisper": mock_whisper}):
        run_check(str(mp3), source=str(md))
