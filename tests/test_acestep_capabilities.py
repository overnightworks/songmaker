"""Tests for the ACE-Step per-model capability profiles."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from songmaker_cli.acestep_capabilities import (
    ACESTEP_PROFILES,
    AceStepProfile,
    ParamSupport,
)
from songmaker_cli.config import get_model_capabilities
from songmaker_cli.constants import MODEL_AVAILABLE_MODES


def test_profiles_cover_every_available_mode() -> None:
    assert set(ACESTEP_PROFILES.keys()) == MODEL_AVAILABLE_MODES


def test_profile_objects_are_frozen() -> None:
    profile = ACESTEP_PROFILES["sft"]
    with pytest.raises(ValidationError):
        profile.shift = ParamSupport(supported=False)


def test_turbo_hides_cfg_related_params() -> None:
    for mode in ("turbo", "xl-turbo"):
        hidden = ACESTEP_PROFILES[mode].hidden_param_names()
        assert "guidance_scale" in hidden
        assert "use_adg" in hidden
        assert "cfg_interval_start" in hidden
        assert "cfg_interval_end" in hidden


def test_turbo_max_inference_steps_is_20() -> None:
    for mode in ("turbo", "xl-turbo"):
        assert ACESTEP_PROFILES[mode].max_inference_steps() == 20


def test_sft_and_base_max_inference_steps_is_200() -> None:
    for mode in ("sft", "xl-sft", "xl-base"):
        assert ACESTEP_PROFILES[mode].max_inference_steps() == 200


def test_sft_does_not_hide_use_adg() -> None:
    for mode in ("sft", "xl-sft"):
        hidden = ACESTEP_PROFILES[mode].hidden_param_names()
        assert "use_adg" not in hidden, (
            f"{mode}: use_adg should be visible — engine honors it when CFG > 1.0"
        )


def test_sft_does_not_hide_cfg_interval_params() -> None:
    for mode in ("sft", "xl-sft"):
        hidden = ACESTEP_PROFILES[mode].hidden_param_names()
        assert "cfg_interval_start" not in hidden
        assert "cfg_interval_end" not in hidden


def test_xl_base_hides_nothing() -> None:
    assert ACESTEP_PROFILES["xl-base"].hidden_param_names() == []


def test_lm_params_supported_on_all_variants() -> None:
    lm_field_names = [
        "thinking", "lm_temperature", "lm_top_k", "lm_top_p", "lm_cfg_scale",
        "lm_negative_prompt", "lm_repetition_penalty",
        "use_cot_caption", "use_cot_language",
    ]
    for mode, profile in ACESTEP_PROFILES.items():
        for field in lm_field_names:
            assert getattr(profile, field).supported, (
                f"{mode}.{field} should be supported"
            )


def test_get_model_capabilities_adapter_shape() -> None:
    caps = get_model_capabilities()
    assert set(caps.keys()) == MODEL_AVAILABLE_MODES
    for mode_caps in caps.values():
        assert set(mode_caps.keys()) == {"max_inference_steps", "hidden_params"}
        assert isinstance(mode_caps["max_inference_steps"], int)
        assert isinstance(mode_caps["hidden_params"], list)


def test_get_model_capabilities_matches_profiles() -> None:
    caps = get_model_capabilities()
    for mode, profile in ACESTEP_PROFILES.items():
        assert caps[mode]["max_inference_steps"] == profile.max_inference_steps()
        assert caps[mode]["hidden_params"] == profile.hidden_param_names()


def test_turbo_overrides_have_distinct_notes() -> None:
    """Each turbo override note should explain that specific parameter, not copy/paste."""
    profile = ACESTEP_PROFILES["turbo"]
    notes = {
        "guidance_scale": profile.guidance_scale.note,
        "use_adg": profile.use_adg.note,
        "cfg_interval_start": profile.cfg_interval_start.note,
        "cfg_interval_end": profile.cfg_interval_end.note,
    }
    for name, note in notes.items():
        assert note, f"turbo.{name} note must not be empty"
    assert len(set(notes.values())) == len(notes), (
        "turbo override notes should be distinct, not copy/pasted from each other"
    )


def test_profile_family_values_are_valid() -> None:
    for profile in ACESTEP_PROFILES.values():
        assert profile.family in ("turbo", "sft", "base")


def test_xl_flag_matches_mode_name() -> None:
    for mode, profile in ACESTEP_PROFILES.items():
        assert profile.is_xl == mode.startswith("xl-")


def test_param_support_min_max_invariant() -> None:
    """If both min and max are set, min must be <= max."""
    for profile in ACESTEP_PROFILES.values():
        for name in type(profile).model_fields:
            value = getattr(profile, name)
            if not isinstance(value, ParamSupport):
                continue
            if value.min is not None and value.max is not None:
                assert value.min <= value.max, (
                    f"{profile.mode}.{name}: min={value.min} > max={value.max}"
                )


def test_profile_round_trips_through_json() -> None:
    for mode, profile in ACESTEP_PROFILES.items():
        dumped = profile.model_dump_json()
        rebuilt = AceStepProfile.model_validate_json(dumped)
        assert rebuilt == profile, f"{mode} did not round-trip"
