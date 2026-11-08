"""Tests for the strict generation_params Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from acestep_engine.models import AceStepConfig
from songmaker_cli.generation_params import (
    BaseGenerationParams,
    CoverTaskParams,
    RepaintTaskParams,
    StoredGenerationParams,
    stored_config_options,
)


def test_base_extra_forbid_rejects_typo() -> None:
    with pytest.raises(ValidationError, match="not permitted|extra"):
        BaseGenerationParams.model_validate({"infrence_steps": 50})


def test_base_refuses_the_reference_path_a_version_no_longer_carries() -> None:
    with pytest.raises(ValidationError, match="extra|not permitted"):
        BaseGenerationParams.model_validate({"reference_audio_path": "user1/clip.wav"})


def test_stored_refuses_the_reference_path_a_take_no_longer_carries() -> None:
    with pytest.raises(ValidationError, match="extra|not permitted"):
        StoredGenerationParams.model_validate({"reference_audio_path": "user1/clip.wav"})


def test_stored_refuses_the_constrained_decoding_switch_a_take_no_longer_carries() -> None:
    with pytest.raises(ValidationError, match="extra|not permitted"):
        StoredGenerationParams.model_validate({"constrained_decoding": True})


def test_a_new_takes_stored_params_carry_no_constrained_decoding() -> None:
    config = AceStepConfig(prompt="p", lyrics="l")
    options = stored_config_options(config, delivered_batch_size=None)
    stored = StoredGenerationParams(**options).model_dump(exclude_none=True)
    assert "constrained_decoding" not in stored


def test_stored_extends_base_with_output_fields() -> None:
    params = StoredGenerationParams(
        acestep_model="sft", bpm=120, audio_duration=180,
        key_scale="Am", task_type="repaint", cot_caption="hi",
    )
    assert params.acestep_model == "sft"
    assert params.task_type == "repaint"


def test_stored_timesteps_validates_format() -> None:
    StoredGenerationParams(timesteps="0.0, 0.5, 1.0")
    with pytest.raises(ValidationError, match="must be comma-separated"):
        StoredGenerationParams(timesteps="0.0,foo,1.0")


def test_repaint_requires_strict_fields() -> None:
    with pytest.raises(ValidationError):
        RepaintTaskParams.model_validate({"src_wav_path": "/x.wav"})


def test_repaint_round_trip_through_model_dump() -> None:
    original = RepaintTaskParams(
        src_wav_path="/x.wav", src_generation_id="g0",
        repainting_start=0.1, repainting_end=0.9,
        lyrics="la", prompt="rock",
    )
    dumped = original.model_dump()
    restored = RepaintTaskParams.model_validate(dumped)
    assert restored == original


def test_cover_round_trip() -> None:
    original = CoverTaskParams(
        src_wav_path="/x.wav", src_generation_id="g0",
        audio_cover_strength=0.7, lyrics="", prompt="",
    )
    dumped = original.model_dump()
    assert CoverTaskParams.model_validate(dumped) == original


def test_cover_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="not permitted|extra"):
        CoverTaskParams.model_validate({
            "src_wav_path": "/x.wav", "src_generation_id": "g0",
            "audio_cover_strength": 0.5, "lyrics": "", "prompt": "",
            "bogus": True,
        })
