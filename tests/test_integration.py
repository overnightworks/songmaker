"""End-to-end integration test for the generate pipeline.

Mocks only the HTTP boundary (urlopen) so the full path is exercised:
parse markdown -> build config -> ACE-Step client -> decode audio -> master -> MP3 + player.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock, patch

import pytest

from conftest import mock_http_response as _mock_response
from songmaker_cli.main import generate


def _setup_project(tmp_path: Path) -> Path:
    """Create a minimal project layout with one song markdown file."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")

    album_dir = tmp_path / "albums" / "test_album"
    lyrics_dir = album_dir / "lyrics"
    lyrics_dir.mkdir(parents=True)

    album_yaml = album_dir / "album.yaml"
    album_yaml.write_text(
        "title: Test Album\n"
        "artist: TestArtist\n"
        "year: 2025\n",
    )

    song_md = lyrics_dir / "01_test_song.md"
    song_md.write_text(
        "---\n"
        "title: Test Song\n"
        "album: test_album\n"
        "track: 1\n"
        "prompt: epic rock anthem\n"
        "bpm: 120\n"
        "duration: 2\n"
        "key: Am\n"
        "language: en\n"
        "---\n"
        "\n"
        "## Lyrics\n"
        "\n"
        "[verse]\n"
        "Hello world\n",
    )
    return song_md


def _health_response() -> MagicMock:
    """Build a mock /health response."""
    return _mock_response(json.dumps({
        "data": {
            "status": "ok", "version": "1.0",
            "loaded_model": "acestep-v15-turbo",
            "loaded_lm_model": "acestep-5Hz-lm-4B",
        },
        "code": 200,
    }).encode())


def _build_acestep_responses(wav_bytes: bytes) -> list[MagicMock]:
    """Build the three mock HTTP responses for a full ACE-Step generate cycle."""
    submit_resp = _mock_response(json.dumps({
        "data": {"task_id": "test-task-1", "status": "queued"},
        "code": 200,
    }).encode())

    result_items = json.dumps([{"file": "/v1/audio?path=test.wav", "seed": 42}])
    poll_resp = _mock_response(json.dumps({
        "data": [{"task_id": "test-task-1", "status": 1, "result": result_items}],
    }).encode())

    audio_resp = _mock_response(wav_bytes)

    return [submit_resp, poll_resp, audio_resp]


def test_generate_end_to_end(tmp_path: Path, make_sine_wav_bytes: Callable[..., bytes]) -> None:
    """Full pipeline: markdown -> ACE-Step client (HTTP mocked) -> mastered MP3 + player."""
    song_md = _setup_project(tmp_path)
    output_dir = tmp_path / "_output"

    wav_bytes = make_sine_wav_bytes()
    responses = [_health_response()] + _build_acestep_responses(wav_bytes)

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = responses
        generate(str(song_md))

    album_output = output_dir / "test_album"
    assert album_output.exists(), "Album output directory should exist"

    mp3s = list(album_output.glob("*.mp3"))
    assert len(mp3s) == 1, f"Expected 1 MP3, found {len(mp3s)}"
    assert mp3s[0].stat().st_size > 0, "MP3 should not be empty"
    assert "01_test_song_v1" in mp3s[0].name

    snapshot_md = album_output / "01_test_song_v1.md"
    assert snapshot_md.exists(), "Snapshot .md should be generated"
    snapshot_text = snapshot_md.read_text()
    assert "acestep_model: acestep-v15-turbo" in snapshot_text

    player_html = output_dir / "player.html"
    assert player_html.exists(), "Player HTML should be generated"

    manifest = output_dir / "manifest.json"
    assert manifest.exists(), "Manifest JSON should be generated"

    assert mock_urlopen.call_count == 4


def test_generate_multiple_versions(
    tmp_path: Path, make_sine_wav_bytes: Callable[..., bytes],
) -> None:
    """Verify count=3 produces three MP3s with incrementing versions."""
    song_md = _setup_project(tmp_path)
    output_dir = tmp_path / "_output"

    wav_bytes = make_sine_wav_bytes()
    responses = [_health_response()] + (
        _build_acestep_responses(wav_bytes)
        + _build_acestep_responses(wav_bytes)
        + _build_acestep_responses(wav_bytes)
    )

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = responses
        generate(str(song_md), count=3)

    album_output = output_dir / "test_album"
    mp3s = sorted(album_output.glob("*.mp3"))
    assert len(mp3s) == 3, f"Expected 3 MP3s, found {len(mp3s)}"

    stems = [mp3.stem for mp3 in mp3s]
    assert "01_test_song_v1" in stems
    assert "01_test_song_v2" in stems
    assert "01_test_song_v3" in stems

    assert mock_urlopen.call_count == 10


def test_generate_with_score_flag(
    tmp_path: Path, make_sine_wav_bytes: Callable[..., bytes],
) -> None:
    """Verify --score triggers scoring and writes scores to snapshot."""
    song_md = _setup_project(tmp_path)
    output_dir = tmp_path / "_output"

    wav_bytes = make_sine_wav_bytes()
    responses = [_health_response()] + _build_acestep_responses(wav_bytes)

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = responses
        generate(str(song_md), score=True)

    album_output = output_dir / "test_album"
    snapshot_md = album_output / "01_test_song_v1.md"
    assert snapshot_md.exists()

    text = snapshot_md.read_text()
    assert "## Scores" in text
    assert "dynamics" in text
    assert "silence_ok" in text


def test_generate_best_flag(
    tmp_path: Path, make_sine_wav_bytes: Callable[..., bytes],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify --best N generates N versions, scores all, and prints ranking."""
    import logging

    song_md = _setup_project(tmp_path)
    output_dir = tmp_path / "_output"

    wav_bytes = make_sine_wav_bytes()
    responses = [_health_response()] + (
        _build_acestep_responses(wav_bytes)
        + _build_acestep_responses(wav_bytes)
    )

    with caplog.at_level(logging.INFO):
        with patch("acestep_engine.client.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = responses
            generate(str(song_md), best=2)

    album_output = output_dir / "test_album"
    mp3s = list(album_output.glob("*.mp3"))
    assert len(mp3s) == 2

    snapshots = list(album_output.glob("*.md"))
    assert all("## Scores" in s.read_text() for s in snapshots)

    assert "RANKING" in caplog.text
    assert "best" in caplog.text
