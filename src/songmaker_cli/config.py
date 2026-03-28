"""Output path resolution, validation, and ACE-Step config building."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session, sessionmaker

from acestep_engine.models import AceStepConfig
from songmaker_cli.db.queries.settings import get_global_defaults, save_global_defaults
from songmaker_cli.errors import ValidationError

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from songmaker_cli.parser import SongMeta



def load_env_file(project_root: Path) -> None:
    """Load .server.env from project root if it exists."""
    from dotenv import load_dotenv

    env_file = project_root / ".server.env"
    if not env_file.exists():
        return
    load_dotenv(env_file, override=False)
    log.info("Loaded env from %s", env_file)


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


_FIELD_MAPPING = {"language": "vocal_language"}


def _apply_params(fields: dict, source: dict) -> None:
    """Merge source params into fields, applying field name mapping."""
    for key, value in source.items():
        mapped = _FIELD_MAPPING.get(key, key)
        fields[mapped] = value


_SHARED_LM_DEFAULTS: dict[str, object] = {
    "shift": 3.0,
    "think_mode": "deep",
    "lm_temperature": 0.85,
    "lm_top_k": 0,
    "lm_top_p": 0.9,
    "lm_cfg_scale": 2.0,
    "lm_negative_prompt": "",
    "infer_method": "ode",
    "batch_size": 1,
}

_BUILTIN_DEFAULTS: dict[str, dict[str, object]] = {
    "turbo": {"inference_steps": 8, "guidance_scale": 0.0, **_SHARED_LM_DEFAULTS},
    "sft": {"inference_steps": 50, "guidance_scale": 0.0, **_SHARED_LM_DEFAULTS},
}


def get_builtin_defaults() -> dict[str, dict[str, object]]:
    return _BUILTIN_DEFAULTS


def resolve_model_mode(model_name: str | None) -> str:
    """Map an ACE-Step model name (e.g. 'acestep-v15-sft') to a builtin mode key."""
    if model_name:
        for mode in _BUILTIN_DEFAULTS:
            if mode in model_name:
                return mode
    return next(iter(_BUILTIN_DEFAULTS))


def build_ace_config(
    meta: "SongMeta",
    cli_overrides: dict | None = None,
    model_name: str | None = None,
    global_defaults: dict | None = None,
    preset_params: dict | None = None,
) -> AceStepConfig:
    """Build an AceStepConfig from SongMeta + optional CLI overrides.

    Priority: CLI overrides > frontmatter > preset params > global defaults > model defaults.
    """
    model_key = resolve_model_mode(model_name)
    model_defaults = _BUILTIN_DEFAULTS[model_key]
    user_defaults = (global_defaults or {}).get(model_key, {})
    active_preset = preset_params or {}
    log.debug(
        "build_ace_config: model=%s (%s), preset=%s, user_defaults=%s, song_params=%s",
        model_name, model_key,
        active_preset or "none", user_defaults or "none",
        meta.generation_params or "none",
    )

    fields: dict = {"prompt": meta.prompt, "lyrics": meta.lyrics}

    layers = [model_defaults, user_defaults, active_preset, meta.generation_params]
    if cli_overrides:
        layers.append({k: v for k, v in cli_overrides.items() if v is not None})
    for layer in layers:
        _apply_params(fields, layer)

    fields = _sanitize_params(fields)
    return AceStepConfig(**fields)


def _sanitize_params(fields: dict) -> dict:
    """Validate ACE-Step params and reject invalid values."""
    shift = fields.get("shift")
    if shift is not None and shift < 0.0:
        raise ValidationError(f"shift={shift} is negative, must be >= 0.0")

    guidance = fields.get("guidance_scale")
    if guidance is not None and guidance < 0.0:
        raise ValidationError(f"guidance_scale={guidance} is negative, must be >= 0.0")

    steps = fields.get("inference_steps")
    if steps is not None and steps < 1:
        raise ValidationError(f"inference_steps={steps} is < 1, must be >= 1")

    duration = fields.get("duration")
    if duration is not None and duration < 1:
        raise ValidationError(f"duration={duration} is < 1, must be >= 1")

    infer = fields.get("infer_method")
    if infer and infer not in ("ode", "sde"):
        raise ValidationError(
            f"infer_method='{infer}' is invalid, must be 'ode' or 'sde'"
        )

    return fields
