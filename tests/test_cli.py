"""Tests for CLI helper functions in main.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from songmaker_cli.errors import ValidationError
from songmaker_cli.main import (
    clean_lyrics,
    collect_overrides,
    find_lyrics_source,
    load_album_meta_for_song,
    validate_path,
    validate_song_meta,
)
from songmaker_cli.parser import SongMeta


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


def test_collect_overrides_filters_none() -> None:
    result = collect_overrides(seed=42, bpm=None, duration=60)
    assert result == {"seed": 42, "duration": 60}


def test_collect_overrides_empty() -> None:
    result = collect_overrides(seed=None, bpm=None)
    assert result == {}


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


def test_find_lyrics_source_explicit(tmp_path: Path) -> None:
    md = tmp_path / "lyrics.md"
    md.write_text("---\nprompt: test\n---\n\n## Lyrics\n\nHello\n")
    mp3 = tmp_path / "song_v1.mp3"
    mp3.touch()
    result = find_lyrics_source(mp3, str(md))
    assert result == md.resolve()


def test_find_lyrics_source_not_found(tmp_path: Path) -> None:
    mp3 = tmp_path / "song_v1.mp3"
    mp3.touch()
    with pytest.raises(ValidationError, match="Could not find"):
        find_lyrics_source(mp3, None)


def test_clean_lyrics_strips_tags() -> None:
    text = "[verse]\nHello World\n[chorus]\nLa La"
    result = clean_lyrics(text)
    assert result == "hello world la la"
