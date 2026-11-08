from __future__ import annotations

import pytest

from acestep_engine.client import _build_submit_payload
from acestep_engine.models import AceStepConfig

_OPTIONAL_KEYS = (
    "audio_cover_strength",
    "cover_noise_strength",
    "use_cot_caption",
    "use_cot_language",
    "lm_repetition_penalty",
    "use_adg",
    "cfg_interval_start",
    "cfg_interval_end",
    "repaint_latent_crossfade_frames",
    "repaint_wav_crossfade_sec",
)


def _cell(**changes: object) -> AceStepConfig:
    return AceStepConfig(prompt="test", lyrics="la la", **changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (_cell(task_type="cover", cover_noise_strength=0.3),
         {"audio_cover_strength": 1.0, "cover_noise_strength": 0.3}),
        (_cell(task_type="cover", audio_cover_strength=0.6),
         {"audio_cover_strength": 0.6}),
        (_cell(use_cot_caption=False), {"use_cot_caption": False}),
        (_cell(use_cot_language=False), {"use_cot_language": False}),
        (_cell(lm_repetition_penalty=1.2), {"lm_repetition_penalty": 1.2}),
        (_cell(use_adg=True), {"use_adg": True}),
        (_cell(cfg_interval_start=0.1), {"cfg_interval_start": 0.1}),
        (_cell(cfg_interval_end=0.9), {"cfg_interval_end": 0.9}),
        (_cell(task_type="repaint", repaint_latent_crossfade_frames=4),
         {"repaint_latent_crossfade_frames": 4}),
        (_cell(task_type="repaint", repaint_wav_crossfade_sec=0.5),
         {"repaint_wav_crossfade_sec": 0.5}),
    ],
)
def test_non_default_value_sends_its_optional_key(
    config: AceStepConfig, expected: dict[str, object],
) -> None:
    payload = _build_submit_payload(config)

    assert {key: payload[key] for key in expected} == expected
    absent = set(_OPTIONAL_KEYS) - set(expected)
    assert absent.isdisjoint(payload)


def test_default_config_sends_none_of_the_optional_keys() -> None:
    payload = _build_submit_payload(_cell())

    assert set(_OPTIONAL_KEYS).isdisjoint(payload)
