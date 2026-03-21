"""Tests for the lyrics checking module."""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock, patch

import pytest

from songmaker_cli.check import find_lyrics_source, log_check_results, run_check
from songmaker_cli.errors import ValidationError
from songmaker_cli.scoring.text_accuracy import clean_lyrics, _get_whisper_model


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


def test_find_lyrics_source_auto_discovery(
    tmp_path: Path, make_song_md: Callable[..., Path],
) -> None:
    output_dir = tmp_path / "_output" / "test_album"
    output_dir.mkdir(parents=True)
    mp3 = output_dir / "01_test_song_v1.mp3"
    mp3.touch()

    albums_dir = tmp_path / "albums" / "test_album" / "lyrics"
    albums_dir.mkdir(parents=True)
    make_song_md(albums_dir)

    result = find_lyrics_source(mp3, None)
    assert result.name == "01_test_song.md"


def test_find_lyrics_source_explicit_not_found(tmp_path: Path) -> None:
    mp3 = tmp_path / "song_v1.mp3"
    mp3.touch()
    with pytest.raises(ValidationError, match="Lyrics source not found"):
        find_lyrics_source(mp3, "/nonexistent/lyrics.md")


def test_find_lyrics_source_not_found(tmp_path: Path) -> None:
    mp3 = tmp_path / "song_v1.mp3"
    mp3.touch()
    with pytest.raises(ValidationError, match="Could not find"):
        find_lyrics_source(mp3, None)


def test_find_lyrics_source_via_project_root(
    tmp_path: Path, make_song_md: Callable[..., Path],
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    albums_dir = tmp_path / "albums" / "test_album" / "lyrics"
    albums_dir.mkdir(parents=True)
    make_song_md(albums_dir)

    deep_output = tmp_path / "some" / "deep" / "output"
    deep_output.mkdir(parents=True)
    mp3 = deep_output / "01_test_song_v1.mp3"
    mp3.touch()

    result = find_lyrics_source(mp3, None)
    assert result.name == "01_test_song.md"


def test_log_check_results_good(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    mp3 = tmp_path / "song.mp3"
    md = tmp_path / "song.md"
    with caplog.at_level("INFO"):
        log_check_results(mp3, md, 0.9, ["Hello"], 1, 0.8, 0.5)
    assert "Good" in caplog.text


def test_log_check_results_fair(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    mp3 = tmp_path / "song.mp3"
    md = tmp_path / "song.md"
    with caplog.at_level("INFO"):
        log_check_results(mp3, md, 0.6, ["Hello"], 1, 0.8, 0.5)
    assert "Needs improvement" in caplog.text


def test_log_check_results_poor(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    mp3 = tmp_path / "song.mp3"
    md = tmp_path / "song.md"
    with caplog.at_level("INFO"):
        log_check_results(mp3, md, 0.2, ["Hello"], 1, 0.8, 0.5)
    assert "Poor" in caplog.text


def test_run_check_calls_scorer(tmp_path: Path, make_song_md: Callable[..., Path]) -> None:
    lyrics_dir = tmp_path / "albums" / "test_album" / "lyrics"
    lyrics_dir.mkdir(parents=True)
    md = make_song_md(lyrics_dir)

    mp3 = tmp_path / "test.mp3"
    mp3.touch()

    with patch("songmaker_cli.scoring.text_accuracy.score_text_accuracy") as mock_scorer:
        from songmaker_cli.scoring.models import TextAccuracyScore

        mock_scorer.return_value = TextAccuracyScore(
            similarity_ratio=0.85, intended_lines=5, transcribed_lines=4,
        )
        run_check(str(mp3), source=str(md))

    mock_scorer.assert_called_once()


def test_whisper_model_cached() -> None:
    mock_whisper = MagicMock()
    mock_model = MagicMock()
    mock_whisper.load_model.return_value = mock_model

    cache: dict[str, object] = {}
    with patch.dict("sys.modules", {"whisper": mock_whisper}):
        _get_whisper_model("small", cache=cache)
        _get_whisper_model("small", cache=cache)

    assert mock_whisper.load_model.call_count == 1
    assert "small" in cache
