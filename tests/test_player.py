"""Tests for the player manifest builder and HTML generation."""

from __future__ import annotations

from pathlib import Path

from songmaker_cli.manifest import (
    build_manifest,
    lyrics_to_lines,
    parse_srt,
    parse_track_title,
    scan_album_tracks,
)
from songmaker_cli.player import generate_player, render_static_html
from songmaker_cli.scanner import deduplicate_versions


def _setup_album(tmp_path: Path, album: str = "test_album") -> tuple[Path, Path]:
    """Create a minimal album layout and return (output_dir, project_root)."""
    output_dir = tmp_path / "output"
    project_root = tmp_path / "project"

    album_out = output_dir / album
    album_out.mkdir(parents=True)

    lyrics_dir = project_root / "albums" / album / "lyrics"
    lyrics_dir.mkdir(parents=True)

    return output_dir, project_root


def test_parse_track_title_numbered() -> None:
    number, title = parse_track_title("01_hello_world_v3")
    assert number == "01"
    assert title == "Hello World"


def test_parse_track_title_bonus() -> None:
    number, title = parse_track_title("bonus_hidden_gem_v1")
    assert number == "B"
    assert title == "Hidden Gem"


def test_parse_track_title_unknown() -> None:
    number, title = parse_track_title("random_file")
    assert number == "?"
    assert title == "Random File"


def test_deduplicate_versions(tmp_path: Path) -> None:
    (tmp_path / "song_v1.mp3").touch()
    (tmp_path / "song_v2.mp3").touch()
    (tmp_path / "song_v3.mp3").touch()
    (tmp_path / "other_v1.mp3").touch()
    mp3s = sorted(tmp_path.glob("*.mp3"))
    result = deduplicate_versions(mp3s)
    stems = [p.stem for p in result]
    assert "song_v3" in stems
    assert "other_v1" in stems
    assert "song_v1" not in stems


def test_deduplicate_versions_skips_raw(tmp_path: Path) -> None:
    (tmp_path / "song_raw.mp3").touch()
    (tmp_path / "song_v1.mp3").touch()
    mp3s = sorted(tmp_path.glob("*.mp3"))
    result = deduplicate_versions(mp3s)
    stems = [p.stem for p in result]
    assert "song_v1" in stems
    assert "song_raw" not in stems


def test_lyrics_to_lines() -> None:
    lyrics = "[verse]\nHello world\nSecond line\n\n[chorus]\nLa la la"
    lines = lyrics_to_lines(lyrics)
    assert lines[0] == {"time": -1, "text": "[VERSE]", "section": True}
    assert lines[1] == {"time": -1, "text": "Hello world", "section": False}
    assert lines[3] == {"time": -1, "text": "[CHORUS]", "section": True}


def test_scan_album_tracks(tmp_path: Path) -> None:
    mp3 = tmp_path / "01_test_song_v1.mp3"
    mp3.touch()
    lyrics_dir = tmp_path / "lyrics"
    lyrics_dir.mkdir()

    tracks = scan_album_tracks([mp3], "album", lyrics_dir)
    assert len(tracks) == 1
    assert tracks[0].title == "Test Song"
    assert tracks[0].number == "01"
    assert tracks[0].file == "album/01_test_song_v1.mp3"


def test_build_manifest_empty(tmp_path: Path) -> None:
    output_dir, project_root = _setup_album(tmp_path)
    (output_dir / "test_album").rmdir()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(output_dir, project_root)
    assert manifest.albums == []


def test_build_manifest_with_tracks(tmp_path: Path) -> None:
    output_dir, project_root = _setup_album(tmp_path)
    (output_dir / "test_album" / "01_hello_v1.mp3").touch()

    manifest = build_manifest(output_dir, project_root)
    real_albums = [a for a in manifest.albums if a.id != "_latest"]
    assert len(real_albums) == 1
    assert real_albums[0].id == "test_album"
    assert len(real_albums[0].tracks) == 1


def test_build_manifest_latest_album(tmp_path: Path) -> None:
    output_dir, project_root = _setup_album(tmp_path)
    (output_dir / "test_album" / "01_hello_v1.mp3").touch()

    manifest = build_manifest(output_dir, project_root)
    latest = [a for a in manifest.albums if a.id == "_latest"]
    assert len(latest) == 1
    assert len(latest[0].tracks) == 1


def test_render_static_html_contains_substitutions() -> None:
    html = render_static_html("null", artist="TestArtist", year="2099")
    assert "TestArtist" in html
    assert "2099" in html
    assert "<!DOCTYPE html>" in html


def test_render_static_html_escapes_script_tags() -> None:
    dangerous_json = '{"title": "</script><script>alert(1)</script>"}'
    html = render_static_html(dangerous_json, artist="Test", year="2025")
    assert "</script><script>" not in html
    assert r"<\/script>" in html


def test_generate_player_creates_files(tmp_path: Path) -> None:
    output_dir, project_root = _setup_album(tmp_path)
    (output_dir / "test_album" / "01_hello_v1.mp3").touch()

    player_path = generate_player(output_dir, project_root)
    assert player_path.exists()
    assert (output_dir / "manifest.json").exists()
    assert "<!DOCTYPE html>" in player_path.read_text()


def test_parse_srt(tmp_path: Path) -> None:
    srt_path = tmp_path / "test.srt"
    srt_path.write_text(
        "1\n"
        "00:00:01,000 --> 00:00:03,000\n"
        "Hello world\n"
        "\n"
        "2\n"
        "00:00:04,500 --> 00:00:06,000\n"
        "Second line\n",
    )
    lines = parse_srt(srt_path)
    assert len(lines) == 2
    assert lines[0] == {"time": 1.0, "text": "Hello world"}
    assert lines[1] == {"time": 4.5, "text": "Second line"}


def test_parse_srt_empty(tmp_path: Path) -> None:
    srt_path = tmp_path / "empty.srt"
    srt_path.write_text("")
    assert parse_srt(srt_path) == []


def test_scan_album_tracks_with_srt(tmp_path: Path) -> None:
    mp3 = tmp_path / "01_test_song_v1.mp3"
    mp3.touch()
    srt = tmp_path / "01_test_song_v1.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nHello\n",
    )
    lyrics_dir = tmp_path / "lyrics"
    lyrics_dir.mkdir()

    tracks = scan_album_tracks([mp3], "album", lyrics_dir)
    assert len(tracks) == 1
    assert tracks[0].has_sung is True
    assert len(tracks[0].lines) == 1


def test_build_manifest_final_dir(tmp_path: Path) -> None:
    output_dir, project_root = _setup_album(tmp_path)
    final_dir = output_dir / "test_album" / "final"
    final_dir.mkdir(parents=True)
    (final_dir / "01_song.mp3").touch()

    manifest = build_manifest(output_dir, project_root)
    real_albums = [a for a in manifest.albums if a.id != "_latest"]
    assert len(real_albums) == 1
    assert real_albums[0].tracks[0].file == "test_album/final/01_song.mp3"
