"""End-to-end integration test for the generate pipeline.

Mocks only the ACE-Step server (returns a known sine WAV).
Exercises: parse markdown -> build config -> decode audio -> master -> MP3 + player.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from unittest.mock import patch

from acestep_engine.models import AceStepResult
from songmaker_cli.main import generate


def _setup_project(tmp_path: Path) -> Path:
    """Create a minimal project layout with one song markdown file."""
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


def test_generate_end_to_end(tmp_path: Path, make_sine_wav_bytes: Callable[..., bytes]) -> None:
    """Full pipeline: markdown -> ACE-Step (mocked) -> mastered MP3 + player."""
    song_md = _setup_project(tmp_path)
    output_dir = tmp_path / "_output"

    wav_bytes = make_sine_wav_bytes()
    mock_result = AceStepResult(wav_bytes=wav_bytes, seed=42)

    with (
        patch("songmaker_cli.main._run_generation") as mock_gen,
        patch("songmaker_cli.config.OUTPUT_ROOT", str(output_dir)),
    ):
        mock_gen.return_value = (mock_result, 5.0)
        generate(str(song_md))

    album_output = output_dir / "test_album"
    assert album_output.exists(), "Album output directory should exist"

    mp3s = list(album_output.glob("*.mp3"))
    assert len(mp3s) == 1, f"Expected 1 MP3, found {len(mp3s)}"
    assert mp3s[0].stat().st_size > 0, "MP3 should not be empty"
    assert "01_test_song_v1" in mp3s[0].name

    player_html = output_dir / "player.html"
    assert player_html.exists(), "Player HTML should be generated"

    manifest = output_dir / "manifest.json"
    assert manifest.exists(), "Manifest JSON should be generated"


def test_generate_multiple_versions(
    tmp_path: Path, make_sine_wav_bytes: Callable[..., bytes],
) -> None:
    """Verify count=3 produces three MP3s with incrementing versions."""
    song_md = _setup_project(tmp_path)
    output_dir = tmp_path / "_output"

    wav_bytes = make_sine_wav_bytes()
    mock_result = AceStepResult(wav_bytes=wav_bytes, seed=42)

    with (
        patch("songmaker_cli.main._run_generation") as mock_gen,
        patch("songmaker_cli.config.OUTPUT_ROOT", str(output_dir)),
    ):
        mock_gen.return_value = (mock_result, 1.0)
        generate(str(song_md), count=3)

    album_output = output_dir / "test_album"
    mp3s = sorted(album_output.glob("*.mp3"))
    assert len(mp3s) == 3, f"Expected 3 MP3s, found {len(mp3s)}"

    stems = [mp3.stem for mp3 in mp3s]
    assert "01_test_song_v1" in stems
    assert "01_test_song_v2" in stems
    assert "01_test_song_v3" in stems
