"""Output path resolution, validation, and ACE-Step config building."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from acestep_engine.models import AceStepConfig
from songmaker_cli.constants import OUTPUT_ROOT
from songmaker_cli.errors import ValidationError

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from songmaker_cli.parser import SongMeta


def validate_path(path: str) -> Path:
    """Resolve and validate that a file path exists."""
    resolved = Path(path).resolve()
    if not resolved.exists():
        raise ValidationError(f"{resolved} not found")
    return resolved


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


def _defaults_path() -> Path:
    root = find_project_root(Path.cwd())
    base = (root / OUTPUT_ROOT) if root else Path(OUTPUT_ROOT)
    return base / "generation_defaults.json"


def load_generation_defaults() -> dict:
    path = _defaults_path()
    if path.exists():
        defaults = json.loads(path.read_text(encoding="utf-8"))
        log.debug("Loaded generation defaults from %s: %s", path, list(defaults.keys()))
        return defaults
    log.debug("No generation defaults file at %s", path)
    return {}


def save_generation_defaults(data: dict) -> None:
    path = _defaults_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    log.info("Saved generation defaults: %s", path)


_FIELD_MAPPING = {"language": "vocal_language"}


_SFT_DEFAULTS = {
    "inference_steps": 50,
    "guidance_scale": 0.0,
}

_TURBO_DEFAULTS = {
    "inference_steps": 8,
    "guidance_scale": 0.0,
}


def build_ace_config(
    meta: "SongMeta",
    cli_overrides: dict | None = None,
    model_name: str | None = None,
    global_defaults: dict | None = None,
) -> AceStepConfig:
    """Build an AceStepConfig from SongMeta + optional CLI overrides.

    Priority: CLI overrides > frontmatter > global defaults > model defaults.
    When using SFT model, applies SFT-appropriate defaults (50 steps, guidance 5.5)
    unless the frontmatter or CLI explicitly sets them.
    """
    is_sft = model_name and "sft" in model_name
    model_defaults = _SFT_DEFAULTS if is_sft else _TURBO_DEFAULTS

    model_key = "sft" if is_sft else "turbo"
    user_defaults = (global_defaults or {}).get(model_key, {})
    log.debug(
        "build_ace_config: model=%s (%s), user_defaults=%s, song_params=%s",
        model_name, model_key, user_defaults or "none", meta.generation_params or "none",
    )

    fields: dict = {"prompt": meta.prompt, "lyrics": meta.lyrics}

    for key, value in model_defaults.items():
        if key not in user_defaults and key not in meta.generation_params:
            fields[key] = value

    for key, value in user_defaults.items():
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
