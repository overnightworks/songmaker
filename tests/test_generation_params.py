"""Tests for the strict generation_params Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from songmaker_cli.api_models.generation_params import (
    BaseGenerationParams,
    CoverTaskParams,
    RepaintTaskParams,
    StoredGenerationParams,
)


def test_base_extra_forbid_rejects_typo() -> None:
    with pytest.raises(ValidationError, match="not permitted|extra"):
        BaseGenerationParams.model_validate({"infrence_steps": 50})


def test_base_reference_audio_path_rejects_traversal() -> None:
    with pytest.raises(ValidationError, match="must not contain"):
        BaseGenerationParams(reference_audio_path="../etc/passwd")


def test_base_reference_audio_path_accepts_safe() -> None:
    params = BaseGenerationParams(reference_audio_path="user1/clip.wav")
    assert params.reference_audio_path == "user1/clip.wav"


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
