"""Output path resolution, validation, and ACE-Step config building."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from acestep_engine.models import AceStepConfig
from songmaker_cli.constants import OUTPUT_ROOT
from songmaker_cli.db.queries.settings import get_global_defaults, save_global_defaults
from songmaker_cli.errors import ValidationError

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from songmaker_cli.parser import SongMeta



class OutputPaths(BaseModel):
    """Resolved output file paths for a generation run."""

    output_dir: Path
    base_name: str
    version: int
    versioned_name: str

    @property
    def raw_wav(self) -> Path:
        return self.output_dir / f"{self.versioned_name}_raw.wav"

    @property
    def mp3(self) -> Path:
        return self.output_dir / f"{self.versioned_name}.mp3"

    @property
    def wav(self) -> Path:
        return self.output_dir / f"{self.versioned_name}.wav"


def next_version(output_dir: Path, base_name: str) -> int:
    """Find the next version number for a track (v1, v2, ...)."""
    versions = []
    for p in output_dir.glob(f"{base_name}_v*.mp3"):
        match = re.search(r"_v(\d+)\.mp3$", p.name)
        if match:
            versions.append(int(match.group(1)))
    return max(versions, default=0) + 1


def find_project_root(start: Path) -> Path | None:
    """Walk up from start to find the project root (contains pyproject.toml)."""
    current = start.resolve()
    for parent in (current, *current.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    return None


def resolve_output_paths(
    album: str, base_name: str, output_root: Path | None = None,
) -> OutputPaths:
    """Build versioned output paths for a generation run."""
    root = output_root or Path(OUTPUT_ROOT)
    output_dir = root / album
    output_dir.mkdir(parents=True, exist_ok=True)
    version = next_version(output_dir, base_name)
    versioned_name = f"{base_name}_v{version}"
    return OutputPaths(
        output_dir=output_dir,
        base_name=base_name,
        version=version,
        versioned_name=versioned_name,
    )


_DEFAULTS_FILENAME = "generation_defaults.json"
_MODEL_MODES = ("turbo", "sft")


def _defaults_path(output_dir: Path) -> Path:
    return output_dir / _DEFAULTS_FILENAME


def _migrate_file_defaults(
    db_factory: sessionmaker[Session], output_dir: Path,
) -> dict:
    path = _defaults_path(output_dir)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    with db_factory() as session:
        for mode in _MODEL_MODES:
            if mode in data:
                save_global_defaults(session, mode, data[mode])
        session.commit()
    path.unlink()
    log.info("Migrated generation defaults from %s to database", path)
    return data


def load_generation_defaults(db_factory: sessionmaker[Session], output_dir: Path) -> dict:
    result: dict = {}
    with db_factory() as session:
        for mode in _MODEL_MODES:
            params = get_global_defaults(session, mode)
            if params is not None:
                result[mode] = params
    if result:
        return result
    return _migrate_file_defaults(db_factory, output_dir)


def save_generation_defaults(db_factory: sessionmaker[Session], data: dict) -> None:
    with db_factory() as session:
        for mode in _MODEL_MODES:
            if mode in data:
                save_global_defaults(session, mode, data[mode])
        session.commit()
    log.info("Saved generation defaults to database")


_FIELD_MAPPING = {"language": "vocal_language"}


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
    is_sft = model_name and "sft" in model_name
    model_key = "sft" if is_sft else "turbo"
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

    for key, value in model_defaults.items():
        overridden = (
            key in active_preset or key in user_defaults or key in meta.generation_params
        )
        if not overridden:
            fields[key] = value

    for key, value in user_defaults.items():
        if key not in active_preset and key not in meta.generation_params:
            mapped = _FIELD_MAPPING.get(key, key)
            fields[mapped] = value

    for key, value in active_preset.items():
        if key not in meta.generation_params:
            mapped = _FIELD_MAPPING.get(key, key)
            fields[mapped] = value

    for key, value in meta.generation_params.items():
        mapped = _FIELD_MAPPING.get(key, key)
        fields[mapped] = value

    if cli_overrides:
        for key, value in cli_overrides.items():
            if value is not None:
                mapped = _FIELD_MAPPING.get(key, key)
                fields[mapped] = value

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
