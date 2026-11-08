"""The generation job applies the person's effective default as the preset layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from support.generation_job_world import (
    make_generation_dto,
    patch_generation_dispatch,
    run_async,
)

from songmaker_cli.config import get_builtin_defaults
from songmaker_cli.db.models import GenerationPreset, User
from songmaker_cli.jobs import run_generation_job

DEFAULT_PRESET_STEPS = 20
OWN_PRESET_STEPS = 30
DEAD_PRESET_ID = "00000000-0000-0000-0000-00000000dead"
MODEL_DEFAULT_STEPS = get_builtin_defaults()["sft"]["inference_steps"]


def _add_preset(seeded_db, *, steps: int, is_default: bool, model_mode: str = "sft") -> str:
    with seeded_db() as session:
        preset = GenerationPreset(
            name=f"steps {steps}",
            model_mode=model_mode,
            params={"inference_steps": steps},
            is_default=is_default,
            created_by="u1",
        )
        session.add(preset)
        session.commit()
        return preset.id


def _steps_sent_to_worker(seeded_db, tmp_path: Path, *, user_id: str = "u1") -> int:
    received: list[int] = []

    def capture(**kwargs):
        received.append(kwargs["ace_config"].inference_steps)
        return make_generation_dto()

    dispatch, post_process, defaults = patch_generation_dispatch(capture)
    with dispatch, post_process, defaults:
        run_async(
            run_generation_job(
                "j1", "s1", "v1", 1, user_id,
                db_factory=seeded_db,
                audio_dir=tmp_path / "audio",
                data_dir=tmp_path / "data",
                redis=MagicMock(),
                target_model="sft",
            )
        )
    return received[0]


def _set_default_config(seeded_db, config: str | None) -> None:
    with seeded_db() as session:
        session.get(User, "u1").default_generation_config = config
        session.commit()


def _own_preset_id(seeded_db) -> str:
    return _add_preset(seeded_db, steps=OWN_PRESET_STEPS, is_default=False)


@pytest.mark.parametrize(
    ("with_default_preset", "config", "expected_steps"),
    [
        (True, None, DEFAULT_PRESET_STEPS),
        (False, None, MODEL_DEFAULT_STEPS),
        (True, "sft", MODEL_DEFAULT_STEPS),
        (True, "own", OWN_PRESET_STEPS),
        (True, "dead", DEFAULT_PRESET_STEPS),
        (True, "turbo", DEFAULT_PRESET_STEPS),
        (False, "turbo", MODEL_DEFAULT_STEPS),
        (True, "other_model_own", DEFAULT_PRESET_STEPS),
    ],
    ids=[
        "no config uses the default preset",
        "no config and no default preset uses the model defaults",
        "a built-in key uses the built-in defaults",
        "an own preset uses its params",
        "a dead preset id means inherit",
        "a built-in key of another model falls back to the default preset",
        "a built-in key of another model and no default preset uses the model defaults",
        "a preset of another model falls back to the default preset",
    ],
)
def test_the_worker_receives_the_effective_default(
    seeded_db, tmp_path, with_default_preset, config, expected_steps,
):
    if with_default_preset:
        _add_preset(seeded_db, steps=DEFAULT_PRESET_STEPS, is_default=True)
    if config == "own":
        config = _own_preset_id(seeded_db)
    elif config == "other_model_own":
        config = _add_preset(
            seeded_db, steps=OWN_PRESET_STEPS, is_default=False, model_mode="turbo"
        )
    elif config == "dead":
        config = DEAD_PRESET_ID
    _set_default_config(seeded_db, config)

    assert _steps_sent_to_worker(seeded_db, tmp_path) == expected_steps


def test_a_job_for_an_unknown_person_uses_the_model_defaults(seeded_db, tmp_path):
    _add_preset(seeded_db, steps=DEFAULT_PRESET_STEPS, is_default=True)

    assert _steps_sent_to_worker(seeded_db, tmp_path, user_id="nobody") == MODEL_DEFAULT_STEPS
