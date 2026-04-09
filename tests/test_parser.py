"""Tests for song/album data models (parser.py)."""

from __future__ import annotations

from songmaker_cli.api_models.generation_params import BaseGenerationParams
from songmaker_cli.parser import AlbumMeta, SongMeta


def test_song_meta_defaults() -> None:
    meta = SongMeta()
    assert meta.title == "Untitled"
    assert meta.album == "unknown"
    assert meta.track == ""
    assert meta.bpm == 0
    assert meta.audio_duration == 0
    assert meta.key_scale == ""
    assert meta.vocal_language == ""
    assert meta.generation_params == BaseGenerationParams()


def test_song_meta_track_coercion() -> None:
    meta = SongMeta(track=7)
    assert meta.track == "7"


def test_song_meta_track_none_coercion() -> None:
    meta = SongMeta(track=None)
    assert meta.track == ""


def test_song_meta_with_generation_params() -> None:
    params = {"inference_steps": 50, "shift": 2.0}
    meta = SongMeta(
        prompt="rock", lyrics="hello",
        bpm=120, key_scale="Am",
        generation_params=params,
    )
    assert meta.bpm == 120
    assert meta.key_scale == "Am"
    assert meta.generation_params.inference_steps == 50
    assert meta.generation_params.shift == 2.0


def test_album_meta_defaults() -> None:
    meta = AlbumMeta(title="Test")
    assert meta.artist == "Flex0r"
    assert meta.subtitle == ""
    assert meta.year == ""
    assert meta.colors is None


def test_album_meta_full() -> None:
    meta = AlbumMeta(
        title="Album", artist="Band", subtitle="Sub", year="2025",
        colors={"primary": "#ff0000"},
    )
    assert meta.title == "Album"
    assert meta.colors["primary"] == "#ff0000"
