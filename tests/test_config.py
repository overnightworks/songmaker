"""Tests for config building and output path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from songmaker_cli.config import (
    audio_file_path,
    build_ace_config,
    find_project_root,
    load_generation_defaults,
    resolve_model_mode,
    save_generation_defaults,
)
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.parser import SongMeta


@pytest.fixture()
def db_factory(tmp_path: Path):
    return init_db(tmp_path / "test.db")


def test_build_ace_config_basic() -> None:
    meta = SongMeta(
        prompt="rock anthem",
        lyrics="[verse]\nHello",
        bpm=140, audio_duration=60, key_scale="Am",
    )
    config = build_ace_config(meta)
    assert config.prompt == "rock anthem"
    assert config.lyrics == "[verse]\nHello"
    assert config.bpm == 140
    assert config.audio_duration == 60
    assert config.key_scale == "Am"


def test_build_ace_config_vocal_language() -> None:
    meta = SongMeta(
        prompt="test",
        lyrics="test",
        vocal_language="de",
    )
    config = build_ace_config(meta)
    assert config.vocal_language == "de"


def test_build_ace_config_seed_kwarg() -> None:
    meta = SongMeta(prompt="test", lyrics="test", bpm=120, audio_duration=60)
    config = build_ace_config(meta, seed=42)
    assert config.bpm == 120
    assert config.seed == 42
    assert config.audio_duration == 60


def test_build_ace_config_cli_overrides_typed() -> None:
    meta = SongMeta(prompt="test", lyrics="test", bpm=120)
    config = build_ace_config(meta, {"shift": 4.0}, seed=99)
    assert config.bpm == 120
    assert config.shift == 4.0
    assert config.seed == 99


def test_build_ace_config_zero_duration_propagates_for_auto() -> None:
    meta = SongMeta(prompt="test", lyrics="test", bpm=120, audio_duration=0)
    config = build_ace_config(meta)
    assert config.audio_duration == 0


def test_build_ace_config_zero_bpm_routes_to_none_for_auto() -> None:
    meta = SongMeta(prompt="test", lyrics="test", bpm=0, audio_duration=60)
    config = build_ace_config(meta)
    assert config.bpm is None


def test_build_ace_config_explicit_bpm_preserved() -> None:
    meta = SongMeta(prompt="test", lyrics="test", bpm=140, audio_duration=60)
    config = build_ace_config(meta)
    assert config.bpm == 140


def test_song_create_request_accepts_zero_duration() -> None:
    from songmaker_cli.api_models.songs import SongCreateRequest

    req = SongCreateRequest(title="t", album_id="a", audio_duration=0)
    assert req.audio_duration == 0


def test_song_update_request_accepts_zero_duration() -> None:
    from songmaker_cli.api_models.songs import SongUpdateRequest

    req = SongUpdateRequest(audio_duration=0)
    assert req.audio_duration == 0


def test_song_create_request_rejects_negative_duration() -> None:
    from songmaker_cli.api_models.songs import SongCreateRequest

    with pytest.raises(PydanticValidationError):
        SongCreateRequest(title="t", album_id="a", audio_duration=-1)


def test_song_create_request_rejects_duration_above_cap() -> None:
    from songmaker_cli.api_models.songs import SongCreateRequest

    with pytest.raises(PydanticValidationError):
        SongCreateRequest(title="t", album_id="a", audio_duration=601)


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
    with pytest.raises(PydanticValidationError, match="shift"):
        SongMeta(prompt="test", lyrics="test", generation_params={"shift": -1.0})


def test_build_ace_config_negative_guidance_raises() -> None:
    with pytest.raises(PydanticValidationError, match="guidance_scale"):
        SongMeta(
            prompt="test", lyrics="test",
            generation_params={"guidance_scale": -0.5},
        )


def test_build_ace_config_zero_steps_raises() -> None:
    with pytest.raises(PydanticValidationError, match="inference_steps"):
        SongMeta(prompt="test", lyrics="test", generation_params={"inference_steps": 0})


def test_build_ace_config_invalid_infer_method_raises() -> None:
    with pytest.raises(PydanticValidationError, match="infer_method"):
        SongMeta(prompt="test", lyrics="test", generation_params={"infer_method": "bad"})


def test_build_ace_config_unknown_param_raises() -> None:
    """The 2026-04-08 surface: extra='forbid' rejects typos at the boundary."""
    with pytest.raises(PydanticValidationError, match="not permitted|extra"):
        SongMeta(
            prompt="test", lyrics="test",
            generation_params={"infrence_steps": 50},  # typo
        )


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
    meta = SongMeta(prompt="test", lyrics="test", bpm=120)
    defaults = {"sft": {"shift": 5.0, "lm_temperature": 0.5}}
    config = build_ace_config(meta, global_defaults=defaults)
    assert config.shift == 5.0
    assert config.lm_temperature == 0.5


def test_build_ace_config_song_overrides_global_defaults() -> None:
    meta = SongMeta(
        prompt="test", lyrics="test", bpm=120,
        generation_params={"shift": 2.0},
    )
    defaults = {"sft": {"shift": 5.0}}
    config = build_ace_config(meta, global_defaults=defaults)
    assert config.shift == 2.0


def test_build_ace_config_sft_global_defaults() -> None:
    meta = SongMeta(prompt="test", lyrics="test", bpm=120)
    defaults = {"sft": {"inference_steps": 60}}
    config = build_ace_config(meta, model_name="acestep-v15-sft", global_defaults=defaults)
    assert config.inference_steps == 60


def test_build_ace_config_cli_overrides_global_defaults() -> None:
    meta = SongMeta(prompt="test", lyrics="test", bpm=120)
    defaults = {"sft": {"shift": 5.0}}
    config = build_ace_config(meta, cli_overrides={"shift": 1.0}, global_defaults=defaults)
    assert config.shift == 1.0


def test_build_ace_config_seed_applied() -> None:
    meta = SongMeta(prompt="test", lyrics="test")
    config = build_ace_config(meta, seed=42)
    assert config.seed == 42


def test_build_ace_config_seed_none_uses_default() -> None:
    meta = SongMeta(prompt="test", lyrics="test")
    config = build_ace_config(meta, seed=None)
    assert config.seed == -1


def test_build_ace_config_seed_negative_one_uses_default() -> None:
    meta = SongMeta(prompt="test", lyrics="test")
    config = build_ace_config(meta, seed=-1)
    assert config.seed == -1


# ── resolve_model_mode ───────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["sft", "turbo", "xl-sft", "xl-turbo", "xl-base"])
def test_resolve_model_mode_known_modes(mode: str) -> None:
    assert resolve_model_mode(mode) == mode


@pytest.mark.parametrize(
    ("full_name", "expected"),
    [
        ("acestep-v15-sft", "sft"),
        ("acestep-v15-turbo", "turbo"),
        ("acestep-v15-xl-sft", "xl-sft"),
        ("acestep-v15-xl-turbo", "xl-turbo"),
        ("acestep-v15-xl-base", "xl-base"),
    ],
)
def test_resolve_model_mode_full_name(full_name: str, expected: str) -> None:
    assert resolve_model_mode(full_name) == expected


def test_resolve_model_mode_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown model"):
        resolve_model_mode("acestep-v999-quantum")


def test_resolve_model_mode_none_raises() -> None:
    with pytest.raises((ValueError, TypeError)):
        resolve_model_mode(None)  # type: ignore[arg-type]
