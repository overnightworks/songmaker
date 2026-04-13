"""Output path resolution, validation, and ACE-Step config building."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session, sessionmaker

from acestep_engine.models import AceStepConfig
from songmaker_cli.acestep_capabilities import ACESTEP_PROFILES
from songmaker_cli.api_models.generation_params import BaseGenerationParams
from songmaker_cli.constants import MODEL_DEFAULT_MODE
from songmaker_cli.db.queries.settings import get_global_defaults, save_global_defaults
from songmaker_cli.errors import ValidationError

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from songmaker_cli.parser import SongMeta



def audio_file_path(audio_dir: Path, user_id: str, generation_id: str, suffix: str) -> Path:
    path = audio_dir / user_id / f"{generation_id}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def find_project_root(start: Path) -> Path | None:
    """Walk up from start to find the project root (contains pyproject.toml)."""
    current = start.resolve()
    for parent in (current, *current.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    return None


_DEFAULTS_FILENAME = "generation_defaults.json"


def _defaults_path(data_dir: Path) -> Path:
    return data_dir / _DEFAULTS_FILENAME


def _migrate_file_defaults(
    db_factory: sessionmaker[Session], data_dir: Path,
) -> dict:
    path = _defaults_path(data_dir)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    with db_factory() as session:
        for mode in _BUILTIN_DEFAULTS:
            if mode in data:
                save_global_defaults(session, mode, data[mode])
        session.commit()
    path.unlink()
    log.info("Migrated generation defaults from %s to database", path)
    return data


def load_generation_defaults(db_factory: sessionmaker[Session], data_dir: Path) -> dict:
    result: dict = {}
    with db_factory() as session:
        for mode in _BUILTIN_DEFAULTS:
            params = get_global_defaults(session, mode)
            if params is not None:
                result[mode] = params
    if result:
        return result
    return _migrate_file_defaults(db_factory, data_dir)


def save_generation_defaults(db_factory: sessionmaker[Session], data: dict) -> None:
    with db_factory() as session:
        for mode in _BUILTIN_DEFAULTS:
            if mode in data:
                save_global_defaults(session, mode, data[mode])
        session.commit()
    log.info("Saved generation defaults to database")


_SHARED_DEFAULTS: dict[str, object] = {
    "shift": 3.0,
    "thinking": True,
    "lm_temperature": 0.85,
    "lm_top_k": 0,
    "lm_top_p": 0.9,
    "lm_cfg_scale": 2.0,
    "lm_negative_prompt": "",
    "infer_method": "ode",
    "batch_size": 1,
    "lm_repetition_penalty": 1.0,
    "use_cot_caption": True,
    "use_cot_language": True,
    "use_adg": False,
    "cfg_interval_start": 0.0,
    "cfg_interval_end": 1.0,
    "sampler_mode": "euler",
    "velocity_norm_threshold": 0.0,
    "velocity_ema_factor": 0.0,
    "latent_shift": 0.0,
    "latent_rescale": 1.0,
    "audio_cover_strength": 1.0,
}

_BUILTIN_DEFAULTS: dict[str, dict[str, object]] = {
    "turbo": {"inference_steps": 8, "guidance_scale": 0.0, **_SHARED_DEFAULTS},
    "sft": {"inference_steps": 50, "guidance_scale": 0.0, **_SHARED_DEFAULTS},
    "xl-turbo": {"inference_steps": 8, "guidance_scale": 0.0, **_SHARED_DEFAULTS},
    "xl-sft": {"inference_steps": 50, "guidance_scale": 0.0, **_SHARED_DEFAULTS},
    "xl-base": {"inference_steps": 50, "guidance_scale": 0.0, **_SHARED_DEFAULTS},
}


def get_builtin_defaults() -> dict[str, dict[str, object]]:
    return _BUILTIN_DEFAULTS


def get_model_capabilities() -> dict[str, dict[str, object]]:
    """Derive the legacy capability shape from ACESTEP_PROFILES.

    The wire format kept here matches what settings_api.py and the frontend
    consume today (max_inference_steps + hidden_params). If we want richer
    UI later, expose AceStepProfile directly via a new endpoint.
    """
    return {
        mode: {
            "max_inference_steps": profile.max_inference_steps(),
            "hidden_params": profile.hidden_param_names(),
        }
        for mode, profile in ACESTEP_PROFILES.items()
    }


_MODEL_NAME_TO_MODE: dict[str, str] = {
    "acestep-v15-turbo": "turbo",
    "acestep-v15-sft": "sft",
    "acestep-v15-xl-turbo": "xl-turbo",
    "acestep-v15-xl-sft": "xl-sft",
    "acestep-v15-xl-base": "xl-base",
}


def resolve_model_mode(model_name: str) -> str:
    """Map an ACE-Step model name (e.g. 'acestep-v15-sft') to a builtin mode key.

    Raises:
        ValueError: if ``model_name`` is not a known builtin mode or full name.
    """
    if model_name in _MODEL_NAME_TO_MODE:
        return _MODEL_NAME_TO_MODE[model_name]
    if model_name in _BUILTIN_DEFAULTS:
        return model_name
    raise ValueError(
        f"Unknown model: {model_name!r}. "
        f"Must be one of {sorted(_BUILTIN_DEFAULTS)} "
        f"or {sorted(_MODEL_NAME_TO_MODE)}",
    )


def _coerce_to_params(
    value: BaseGenerationParams | dict | None,
) -> BaseGenerationParams | None:
    """Accept either a typed model or a raw dict, return the typed model.

    Raises :class:`ValidationError` if the dict cannot be validated. Used so
    that legacy callers (CLI, tests) passing dicts still work without losing
    the boundary check that catches typos.
    """
    if value is None:
        return None
    if isinstance(value, BaseGenerationParams):
        return value
    if isinstance(value, dict):
        try:
            return BaseGenerationParams.model_validate(value)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc)) from exc
    msg = (
        f"generation params must be BaseGenerationParams or dict, "
        f"got {type(value).__name__}"
    )
    raise ValidationError(msg)


def _merge_layers(
    *layers: BaseGenerationParams | None,
) -> dict[str, object]:
    """Merge typed param layers into a flat dict.

    Each layer's non-None fields override earlier layers. Used as the
    interior of :func:`build_ace_config` so that the merge happens between
    validated typed objects, not raw dicts.
    """
    result: dict[str, object] = {}
    for layer in layers:
        if layer is None:
            continue
        for key, value in layer.model_dump().items():
            if value is not None:
                result[key] = value
    return result


def build_ace_config(
    meta: "SongMeta",
    cli_overrides: BaseGenerationParams | dict | None = None,
    model_name: str = MODEL_DEFAULT_MODE,
    global_defaults: dict[str, dict] | None = None,
    preset_params: BaseGenerationParams | dict | None = None,
    seed: int | None = None,
) -> AceStepConfig:
    """Build an AceStepConfig from a typed SongMeta + typed override layers.

    Layering (later wins): model defaults < user global defaults < preset
    params < song meta < CLI overrides. Each layer is a
    :class:`BaseGenerationParams`; merging happens field-by-field, never via
    raw ``dict.update``. Top-of-meta scalars (``bpm``, ``audio_duration``,
    ``key_scale``, ``vocal_language``) and the seed are applied last.

    ``global_defaults`` is the per-model dict-of-dicts loaded from the DB
    (``{"sft": {...}, "turbo": {...}}``); the entry for the resolved model
    is validated as :class:`BaseGenerationParams` here.
    """
    model_key = resolve_model_mode(model_name)
    builtin_layer = BaseGenerationParams.model_validate(_BUILTIN_DEFAULTS[model_key])
    user_defaults_dict = (global_defaults or {}).get(model_key)
    user_defaults_layer = _coerce_to_params(user_defaults_dict)
    preset_layer = _coerce_to_params(preset_params)
    song_layer = meta.generation_params
    cli_layer = _coerce_to_params(cli_overrides)

    log.debug(
        "build_ace_config: model=%s (%s), preset=%s, user_defaults=%s, song_params=%s",
        model_name, model_key,
        preset_layer or "none", user_defaults_layer or "none",
        song_layer or "none",
    )

    fields: dict[str, object] = {
        "prompt": meta.prompt,
        "lyrics": meta.lyrics,
    }
    fields.update(_merge_layers(
        builtin_layer, user_defaults_layer, preset_layer, song_layer, cli_layer,
    ))

    if meta.bpm:
        fields["bpm"] = meta.bpm
    if meta.audio_duration:
        fields["audio_duration"] = meta.audio_duration
    if meta.key_scale:
        fields["key_scale"] = meta.key_scale
    if meta.vocal_language:
        fields["vocal_language"] = meta.vocal_language

    if seed is not None and seed >= 0:
        fields["seed"] = seed

    try:
        return AceStepConfig(**fields)
    except TypeError as exc:
        raise ValidationError(str(exc)) from exc
