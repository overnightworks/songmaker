"""Contract test: AceStepConfig must round-trip through the vendored ACE-Step model.

This is the lock that enforces Phase 3 of plans/acestep-naming-and-magic-strings.md.
If a future ACE-Step upgrade renames a field, this test fails on rebase rather
than at generation time.

The vendored model lives in _models/acestep/ and is normally only importable
inside the ACE-Step venv. We inject the source dir into sys.path; the warning
about pydantic v1 config keys is benign — the vendored model uses
allow_population_by_field_name which pydantic v2 has renamed but still honours.
"""
from __future__ import annotations

import sys
import warnings
from dataclasses import asdict
from pathlib import Path

import pytest

_VENDORED_ACESTEP_PATH = (
    Path(__file__).resolve().parent.parent / "_models" / "acestep"
)
if str(_VENDORED_ACESTEP_PATH) not in sys.path:
    sys.path.insert(0, str(_VENDORED_ACESTEP_PATH))

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=".*allow_population_by_field_name.*")
    try:
        from acestep.api.http.release_task_models import (  # type: ignore[import-not-found]
            GenerateMusicRequest,
        )
    except ImportError as exc:
        pytest.skip(
            f"vendored acestep package not importable: {exc}",
            allow_module_level=True,
        )

from acestep_engine.models import AceStepConfig  # noqa: E402


def _base_config(**overrides) -> AceStepConfig:
    defaults: dict[str, object] = {
        "prompt": "rock ballad with piano",
        "lyrics": "[verse]\nHello world\n[chorus]\nOh oh oh",
        "bpm": 120,
        "audio_duration": 60,
        "key_scale": "C major",
        "vocal_language": "en",
        "inference_steps": 8,
        "thinking": True,
    }
    defaults.update(overrides)
    return AceStepConfig(**defaults)


@pytest.mark.parametrize(
    ("task_type", "extras"),
    [
        ("text2music", {}),
        (
            "repaint",
            {
                "src_audio_path": "/tmp/src.wav",
                "repainting_start": 10.0,
                "repainting_end": 20.0,
                "repaint_mode": "balanced",
                "repaint_strength": 0.5,
            },
        ),
        (
            "cover",
            {
                "src_audio_path": "/tmp/src.wav",
                "audio_cover_strength": 0.8,
                "cover_noise_strength": 0.1,
            },
        ),
    ],
)
def test_acestep_config_validates_against_vendored_model(
    task_type: str, extras: dict[str, object],
) -> None:
    config = _base_config(task_type=task_type, **extras)
    payload = {k: v for k, v in asdict(config).items() if v not in (None, "", -1)}
    payload["use_random_seed"] = config.seed < 0
    payload["audio_format"] = "wav"

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*allow_population_by_field_name.*")
        model = GenerateMusicRequest(**payload)

    assert model.task_type == task_type
    assert model.prompt == config.prompt
    assert model.audio_duration == config.audio_duration
    assert model.key_scale == config.key_scale
    assert model.thinking is config.thinking
    if "src_audio_path" in extras:
        assert model.src_audio_path == extras["src_audio_path"]
    if "audio_cover_strength" in extras:
        assert model.audio_cover_strength == extras["audio_cover_strength"]


def test_acestep_config_has_no_unknown_fields() -> None:
    cfg_fields = {f.name for f in AceStepConfig.__dataclass_fields__.values()}
    model_fields = set(GenerateMusicRequest.model_fields.keys())
    songmaker_only = {"seed"}
    extra = cfg_fields - model_fields - songmaker_only
    assert not extra, (
        f"AceStepConfig fields missing from vendored GenerateMusicRequest: {extra}"
    )
