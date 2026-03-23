"""Tests for the batch scoring module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from songmaker_cli.errors import ValidationError


def _setup_batch_project(tmp_path: Path) -> Path:
    """Create a minimal project layout for batch scoring tests."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    output_dir = tmp_path / "_output"
    album_dir = output_dir / "test_album"
    album_dir.mkdir(parents=True)

    albums_dir = tmp_path / "albums" / "test_album"
    lyrics_dir = albums_dir / "lyrics"
    lyrics_dir.mkdir(parents=True)
    (albums_dir / "album.yaml").write_text("title: Test\nartist: Test\n")

    return output_dir


def _create_mp3_with_snapshot(
    album_dir: Path, name: str, scores: str | None = None,
) -> Path:
    mp3 = album_dir / f"{name}.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00" * 10)
    snapshot = album_dir / f"{name}.md"
    text = "---\ntitle: Test\n---\n\n## Lyrics\n\nHello\n\n## Generation\n\n- seed: 42\n"
    if scores:
        text += f"\n## Scores\n\n{scores}"
    snapshot.write_text(text)
    return mp3


def test_score_all_skips_already_scored(tmp_path: Path) -> None:
    output_dir = _setup_batch_project(tmp_path)
    album_dir = output_dir / "test_album"
    _create_mp3_with_snapshot(album_dir, "01_song_v1", "- dynamics: 50.0\n")

    mock_scores = MagicMock()
    mock_scores.to_dict.return_value = {"dynamics": 50.0}

    with (
        patch("songmaker_cli.batch.find_project_root", return_value=tmp_path),
        patch("songmaker_cli.batch.run_scoring_pipeline", return_value=mock_scores) as mock_run,
    ):
        from songmaker_cli.batch import score_all

        score_all(None, MagicMock(), force=False)

    mock_run.assert_not_called()


def test_score_all_force_rescores(tmp_path: Path) -> None:
    output_dir = _setup_batch_project(tmp_path)
    album_dir = output_dir / "test_album"
    _create_mp3_with_snapshot(album_dir, "01_song_v1", "- dynamics: 50.0\n")

    mock_scores = MagicMock()
    mock_scores.to_dict.return_value = {"dynamics": 60.0}

    with (
        patch("songmaker_cli.batch.find_project_root", return_value=tmp_path),
        patch("songmaker_cli.batch.run_scoring_pipeline", return_value=mock_scores) as mock_run,
        patch("songmaker_cli.batch.append_scores_section"),
    ):
        from songmaker_cli.batch import score_all

        score_all(None, MagicMock(), force=True)

    assert mock_run.call_count == 1


def test_score_all_no_output_dir(tmp_path: Path) -> None:
    with patch("songmaker_cli.batch.find_project_root", return_value=tmp_path):
        from songmaker_cli.batch import score_all

        with pytest.raises(ValidationError, match="No output directory"):
            score_all(None, MagicMock(), force=False)


def test_score_all_empty_output(tmp_path: Path) -> None:
    _setup_batch_project(tmp_path)

    with (
        patch("songmaker_cli.batch.find_project_root", return_value=tmp_path),
        patch("songmaker_cli.batch.run_scoring_pipeline") as mock_run,
    ):
        from songmaker_cli.batch import score_all

        score_all(None, MagicMock(), force=False)

    mock_run.assert_not_called()


def test_score_single(tmp_path: Path) -> None:
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00" * 10)

    mock_scores = MagicMock()
    mock_scores.to_dict.return_value = {"dynamics": 50.0}
    mock_scores.silence = None

    with (
        patch("songmaker_cli.batch.validate_path", return_value=mp3),
        patch("songmaker_cli.batch.run_scoring_pipeline", return_value=mock_scores) as mock_run,
        patch("songmaker_cli.batch.log_scores"),
    ):
        from songmaker_cli.batch import score_single

        score_single(str(mp3), source=None, scorer_list=None, config=MagicMock())

    mock_run.assert_called_once()
