"""Output path resolution and ACE-Step config building."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from songmaker_cli.constants import OUTPUT_ROOT
from songmaker_cli.errors import ValidationError

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from acestep_engine import AceStepConfig
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
    def wav(self) -> Path:
        return self.output_dir / f"{self.versioned_name}.wav"

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


_FIELD_MAPPING = {"language": "vocal_language"}


def build_ace_config(
    meta: "SongMeta",
    cli_overrides: dict | None = None,
) -> "AceStepConfig":
    """Build an AceStepConfig from SongMeta + optional CLI overrides.

    Priority: CLI overrides > frontmatter values > AceStepConfig defaults.
    """
    from acestep_engine import AceStepConfig as _AceStepConfig

    fields: dict = {"prompt": meta.prompt, "lyrics": meta.lyrics}

    for key, value in meta.generation_params.items():
        mapped = _FIELD_MAPPING.get(key, key)
        fields[mapped] = value

    if cli_overrides:
        for key, value in cli_overrides.items():
            if value is not None:
                mapped = _FIELD_MAPPING.get(key, key)
                fields[mapped] = value

    fields = _sanitize_params(fields)
    return _AceStepConfig(**fields)


def _sanitize_params(fields: dict) -> dict:
    """Sanitize ACE-Step params: clamp invalid ranges, log warnings."""
    result = dict(fields)

    shift = result.get("shift")
    if shift is not None and shift < 0.0:
        log.warning("shift=%.1f is negative, using 0.0", shift)
        result["shift"] = 0.0

    guidance = result.get("guidance_scale")
    if guidance is not None and guidance < 0.0:
        log.warning("guidance_scale=%.1f is negative, using 0.0", guidance)
        result["guidance_scale"] = 0.0

    steps = result.get("inference_steps")
    if steps is not None and steps < 1:
        log.warning("inference_steps=%d is < 1, using 1", steps)
        result["inference_steps"] = 1

    duration = result.get("duration")
    if duration is not None and duration < 1:
        log.warning("duration=%d is < 1, using 1", duration)
        result["duration"] = 1

    infer = result.get("infer_method")
    if infer and infer not in ("ode", "sde"):
        raise ValidationError(
            f"infer_method='{infer}' is invalid, must be 'ode' or 'sde'"
        )

    return result
