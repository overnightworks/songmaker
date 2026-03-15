"""Tests for the song markdown and album YAML parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from songmaker_cli.errors import ValidationError
from songmaker_cli.parser import extract_lyrics, parse_album_yaml, parse_song_md


@pytest.fixture
def song_md(tmp_path: Path) -> Path:
    md = tmp_path / "lyrics" / "01_test_song.md"
    md.parent.mkdir(parents=True)
    md.write_text(
        "---\n"
        "title: Test Song\n"
        "album: test_album\n"
        "track: 3\n"
        "genre: rock\n"
        "prompt: epic rock anthem\n"
        "bpm: 140\n"
        "duration: 60\n"
        "key: Am\n"
        "language: en\n"
        "seed: 42\n"
        "status: approved\n"
        "---\n"
        "\n"
        "# Test Song\n"
        "\n"
        "## Concept\n"
        "A test.\n"
        "\n"
        "## Lyrics\n"
        "\n"
        "[verse]\n"
        "Hello world\n"
        "Second line\n"
        "\n"
        "[chorus]\n"
        "La la la\n",
        encoding="utf-8",
    )
    return md


@pytest.fixture
def album_yaml(tmp_path: Path) -> Path:
    yaml_path = tmp_path / "album.yaml"
    yaml_path.write_text(
        "title: My Album\n"
        "artist: TestArtist\n"
        "subtitle: The Subtitle\n"
        "year: 2025\n",
        encoding="utf-8",
    )
    return yaml_path


def test_parse_song_md_basic(song_md: Path) -> None:
    meta = parse_song_md(song_md)
    assert meta.title == "Test Song"
    assert meta.album == "test_album"
    assert meta.track == "3"
    assert meta.genre == "rock"
    assert meta.prompt == "epic rock anthem"
    assert meta.status == "approved"
    assert "[verse]" in meta.lyrics
    assert "Hello world" in meta.lyrics
    assert meta.source_path == song_md


def test_parse_song_md_generation_params(song_md: Path) -> None:
    meta = parse_song_md(song_md)
    assert meta.generation_params["bpm"] == 140
    assert meta.generation_params["duration"] == 60
    assert meta.generation_params["key"] == "Am"
    assert meta.generation_params["language"] == "en"
    assert meta.generation_params["seed"] == 42
    assert "title" not in meta.generation_params
    assert "prompt" not in meta.generation_params


def test_parse_song_md_no_frontmatter(tmp_path: Path) -> None:
    md = tmp_path / "bad.md"
    md.write_text("Just some text\nNo frontmatter here\n")
    with pytest.raises(ValidationError, match="No YAML frontmatter"):
        parse_song_md(md)


def test_parse_song_md_defaults(tmp_path: Path) -> None:
    md = tmp_path / "lyrics" / "minimal.md"
    md.parent.mkdir(parents=True)
    md.write_text("---\nprompt: test\n---\n\n## Lyrics\n\nHello\n")
    meta = parse_song_md(md)
    assert meta.title == "minimal"
    assert meta.album == tmp_path.name
    assert meta.track == ""


def test_parse_song_md_track_coercion(tmp_path: Path) -> None:
    md = tmp_path / "lyrics" / "track_int.md"
    md.parent.mkdir(parents=True)
    md.write_text("---\ntrack: 7\n---\n\nno lyrics section\n")
    meta = parse_song_md(md)
    assert meta.track == "7"


def test_extract_lyrics_found() -> None:
    text = "Some header\n\n## Lyrics\n\n[verse]\nHello\n\n## Notes\n\nStuff"
    result = extract_lyrics(text)
    assert result == "[verse]\nHello"


def test_extract_lyrics_not_found() -> None:
    assert extract_lyrics("No lyrics section here") is None


def test_extract_lyrics_at_end() -> None:
    text = "## Lyrics\n\nFinal lyrics\nMore lyrics\n"
    result = extract_lyrics(text)
    assert result == "Final lyrics\nMore lyrics"


def test_parse_album_yaml(album_yaml: Path) -> None:
    meta = parse_album_yaml(album_yaml)
    assert meta.title == "My Album"
    assert meta.artist == "TestArtist"
    assert meta.subtitle == "The Subtitle"
    assert meta.year == "2025"


def test_parse_album_yaml_defaults(tmp_path: Path) -> None:
    yaml_path = tmp_path / "my_album" / "album.yaml"
    yaml_path.parent.mkdir()
    yaml_path.write_text("{}\n")
    meta = parse_album_yaml(yaml_path)
    assert meta.title == "My Album"
    assert meta.artist == "Flex0r"
    assert meta.year == ""


def test_parse_song_md_unknown_key_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    md = tmp_path / "lyrics" / "song.md"
    md.parent.mkdir(parents=True)
    md.write_text(
        "---\nprompt: test\nduraton: 60\n---\n\n## Lyrics\n\nHello\n",
    )
    with caplog.at_level("WARNING"):
        parse_song_md(md)
    assert "duraton" in caplog.text
    assert "duration" in caplog.text


def test_parse_song_md_unknown_key_warns_songmeta_fields(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    md = tmp_path / "lyrics" / "song.md"
    md.parent.mkdir(parents=True)
    md.write_text(
        "---\nprompt: test\npromt: typo\n---\n\n## Lyrics\n\nHello\n",
    )
    with caplog.at_level("WARNING"):
        parse_song_md(md)
    assert "promt" in caplog.text
    assert "prompt" in caplog.text


def test_find_lyrics_md_with_version(tmp_path: Path) -> None:
    from songmaker_cli.parser import find_lyrics_md

    lyrics_dir = tmp_path / "lyrics"
    lyrics_dir.mkdir()
    md = lyrics_dir / "01_song.md"
    md.touch()

    assert find_lyrics_md("01_song_v3", lyrics_dir) == md


def test_find_lyrics_md_not_found(tmp_path: Path) -> None:
    from songmaker_cli.parser import find_lyrics_md

    lyrics_dir = tmp_path / "lyrics"
    lyrics_dir.mkdir()

    assert find_lyrics_md("nonexistent", lyrics_dir) is None
