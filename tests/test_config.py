"""Tests for config building and output path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from songmaker_cli.config import (
    build_ace_config,
    find_project_root,
    next_version,
    resolve_output_paths,
)
from songmaker_cli.errors import ValidationError
from songmaker_cli.parser import SongMeta


def test_build_ace_config_basic() -> None:
    meta = SongMeta(
        prompt="rock anthem",
        lyrics="[verse]\nHello",
        generation_params={"bpm": 140, "duration": 60, "key": "Am"},
    )
    config = build_ace_config(meta)
    assert config.prompt == "rock anthem"
    assert config.lyrics == "[verse]\nHello"
    assert config.bpm == 140
    assert config.duration == 60
    assert config.key == "Am"


def test_build_ace_config_language_mapping() -> None:
    meta = SongMeta(
        prompt="test",
        lyrics="test",
        generation_params={"language": "de"},
    )
    config = build_ace_config(meta)
    assert config.vocal_language == "de"


def test_build_ace_config_cli_overrides() -> None:
    meta = SongMeta(
        prompt="test",
        lyrics="test",
        generation_params={"bpm": 120, "duration": 60},
    )
    config = build_ace_config(meta, {"bpm": 180, "seed": 42})
    assert config.bpm == 180
    assert config.seed == 42
    assert config.duration == 60


def test_build_ace_config_cli_overrides_none_ignored() -> None:
    meta = SongMeta(
        prompt="test",
        lyrics="test",
        generation_params={"bpm": 120},
    )
    config = build_ace_config(meta, {"bpm": None, "seed": 99})
    assert config.bpm == 120
    assert config.seed == 99


def test_resolve_output_paths(tmp_path: Path) -> None:
    paths = resolve_output_paths("my_album", "song_name", output_root=tmp_path)
    assert paths.output_dir == tmp_path / "my_album"
    assert paths.version == 1
    assert paths.versioned_name == "song_name_v1"
    assert paths.mp3 == tmp_path / "my_album" / "song_name_v1.mp3"


def test_resolve_output_paths_increments_version(tmp_path: Path) -> None:
    album_dir = tmp_path / "album"
    album_dir.mkdir()
    (album_dir / "song_v1.mp3").touch()
    (album_dir / "song_v2.mp3").touch()
    paths = resolve_output_paths("album", "song", output_root=tmp_path)
    assert paths.version == 3


def test_next_version_empty(tmp_path: Path) -> None:
    assert next_version(tmp_path, "song") == 1


def test_next_version_with_existing(tmp_path: Path) -> None:
    (tmp_path / "song_v1.mp3").touch()
    (tmp_path / "song_v3.mp3").touch()
    assert next_version(tmp_path, "song") == 4


def test_build_ace_config_negative_shift_raises() -> None:
    meta = SongMeta(prompt="test", lyrics="test", generation_params={"shift": -1.0})
    with pytest.raises(ValidationError, match="shift="):
        build_ace_config(meta)


def test_build_ace_config_negative_guidance_raises() -> None:
    meta = SongMeta(prompt="test", lyrics="test", generation_params={"guidance_scale": -0.5})
    with pytest.raises(ValidationError, match="guidance_scale="):
        build_ace_config(meta)


def test_build_ace_config_zero_steps_raises() -> None:
    meta = SongMeta(prompt="test", lyrics="test", generation_params={"inference_steps": 0})
    with pytest.raises(ValidationError, match="inference_steps="):
        build_ace_config(meta)


def test_build_ace_config_zero_duration_raises() -> None:
    meta = SongMeta(prompt="test", lyrics="test", generation_params={"duration": 0})
    with pytest.raises(ValidationError, match="duration="):
        build_ace_config(meta)


def test_build_ace_config_invalid_infer_method_raises() -> None:
    meta = SongMeta(prompt="test", lyrics="test", generation_params={"infer_method": "bad"})
    with pytest.raises(ValidationError, match="infer_method="):
        build_ace_config(meta)


def test_find_project_root_found(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == tmp_path


def test_find_project_root_not_found(tmp_path: Path) -> None:
    nested = tmp_path / "isolated"
    nested.mkdir()
    assert find_project_root(nested) is None


def test_find_project_root_at_root(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    assert find_project_root(tmp_path) == tmp_path
