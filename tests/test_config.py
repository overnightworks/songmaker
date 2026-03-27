"""Tests for config building and output path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from songmaker_cli.config import (
    audio_file_path,
    build_ace_config,
    find_project_root,
    load_generation_defaults,
    save_generation_defaults,
)
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.errors import ValidationError
from songmaker_cli.parser import SongMeta


@pytest.fixture()
def db_factory(tmp_path: Path):
    return init_db(tmp_path / "test.db")


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


def test_audio_file_path_basic(tmp_path: Path) -> None:
    result = audio_file_path(tmp_path, "user1", "gen1", ".mp3")
    assert result == tmp_path / "user1" / "gen1.mp3"
    assert result.parent.exists()


def test_audio_file_path_creates_dir(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    result = audio_file_path(audio_dir, "user2", "gen2", ".wav")
    assert result == audio_dir / "user2" / "gen2.wav"
    assert result.parent.exists()


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


# ── Global defaults ─────────────────────────────────────────────────


def test_load_defaults_empty(db_factory, tmp_path: Path) -> None:
    assert load_generation_defaults(db_factory, tmp_path) == {}


def test_save_and_load_defaults(db_factory, tmp_path: Path) -> None:
    data = {"turbo": {"inference_steps": 12}, "sft": {"inference_steps": 60}}
    save_generation_defaults(db_factory, data)
    loaded = load_generation_defaults(db_factory, tmp_path)
    assert loaded == data


def test_migrate_file_defaults_to_db(db_factory, tmp_path: Path) -> None:
    json_path = tmp_path / "generation_defaults.json"
    import json
    data = {"turbo": {"inference_steps": 12}, "sft": {"inference_steps": 60}}
    json_path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_generation_defaults(db_factory, tmp_path)
    assert loaded == data
    assert not json_path.exists()

    reloaded = load_generation_defaults(db_factory, tmp_path)
    assert reloaded == data


def test_save_defaults_upserts(db_factory, tmp_path: Path) -> None:
    save_generation_defaults(db_factory, {"turbo": {"shift": 1.0}})
    save_generation_defaults(db_factory, {"turbo": {"shift": 5.0}})
    loaded = load_generation_defaults(db_factory, tmp_path)
    assert loaded["turbo"]["shift"] == 5.0


def test_db_defaults_take_priority_over_file(db_factory, tmp_path: Path) -> None:
    import json
    json_path = tmp_path / "generation_defaults.json"
    json_path.write_text(json.dumps({"turbo": {"shift": 1.0}}), encoding="utf-8")

    save_generation_defaults(db_factory, {"turbo": {"shift": 5.0}})
    loaded = load_generation_defaults(db_factory, tmp_path)
    assert loaded["turbo"]["shift"] == 5.0


# ── build_ace_config with global_defaults ────────────────────────────


def test_build_ace_config_global_defaults_applied() -> None:
    meta = SongMeta(prompt="test", lyrics="test", generation_params={"bpm": 120})
    defaults = {"turbo": {"shift": 5.0, "lm_temperature": 0.5}}
    config = build_ace_config(meta, global_defaults=defaults)
    assert config.shift == 5.0
    assert config.lm_temperature == 0.5


def test_build_ace_config_song_overrides_global_defaults() -> None:
    meta = SongMeta(
        prompt="test", lyrics="test",
        generation_params={"bpm": 120, "shift": 2.0},
    )
    defaults = {"turbo": {"shift": 5.0}}
    config = build_ace_config(meta, global_defaults=defaults)
    assert config.shift == 2.0


def test_build_ace_config_sft_global_defaults() -> None:
    meta = SongMeta(prompt="test", lyrics="test", generation_params={"bpm": 120})
    defaults = {"sft": {"inference_steps": 60}}
    config = build_ace_config(meta, model_name="ace-sft-v1", global_defaults=defaults)
    assert config.inference_steps == 60


def test_build_ace_config_cli_overrides_global_defaults() -> None:
    meta = SongMeta(prompt="test", lyrics="test", generation_params={"bpm": 120})
    defaults = {"turbo": {"shift": 5.0}}
    config = build_ace_config(meta, cli_overrides={"shift": 1.0}, global_defaults=defaults)
    assert config.shift == 1.0
