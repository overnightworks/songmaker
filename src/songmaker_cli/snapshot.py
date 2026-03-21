"""Write generation snapshot markdown files alongside MP3 output."""

from __future__ import annotations

import datetime
import importlib.metadata
import logging
from dataclasses import asdict
from pathlib import Path

import yaml

from acestep_engine.models import AceStepConfig, ServerInfo
from songmaker_cli.config import OutputPaths
from songmaker_cli.scoring.models import SongScores

log = logging.getLogger(__name__)

_FIELD_REVERSE_MAPPING = {"vocal_language": "language"}


def write_snapshot(
    source_path: Path,
    paths: OutputPaths,
    ace_config: AceStepConfig,
    seed: int,
    server_info: ServerInfo | None = None,
) -> Path:
    """Write a generation snapshot .md alongside the MP3.

    The snapshot is a copy of the source markdown with frontmatter
    values replaced by the actual resolved generation parameters,
    plus a ## Generation section with runtime-only metadata.
    """
    source_text = source_path.read_text(encoding="utf-8")
    parts = source_text.split("---", 2)
    if len(parts) < 3:
        return _write_raw(paths, source_text, ace_config, seed, server_info)

    original_front = yaml.safe_load(parts[1]) or {}
    resolved_front = _merge_resolved_params(original_front, ace_config)
    body = parts[2]

    frontmatter_str = yaml.dump(
        resolved_front, default_flow_style=False, allow_unicode=True, sort_keys=False,
    )
    generation_section = _build_generation_section(seed, server_info, source_path)

    snapshot = f"---\n{frontmatter_str}---{body}"
    if "## Generation" not in body:
        snapshot = snapshot.rstrip() + "\n\n" + generation_section + "\n"

    snapshot_path = paths.output_dir / f"{paths.versioned_name}.md"
    snapshot_path.write_text(snapshot, encoding="utf-8")
    log.info("Snapshot written: %s", snapshot_path.name)
    return snapshot_path


def _merge_resolved_params(
    original: dict, ace_config: AceStepConfig,
) -> dict:
    """Overlay resolved AceStepConfig values onto the original frontmatter."""
    result = dict(original)
    config_dict = asdict(ace_config)

    for key, value in config_dict.items():
        if key in ("prompt", "lyrics"):
            continue
        front_key = _FIELD_REVERSE_MAPPING.get(key, key)
        result[front_key] = value

    return result


def _build_generation_section(
    seed: int,
    server_info: ServerInfo | None,
    source_path: Path,
) -> str:
    """Build the ## Generation metadata section."""
    lines = ["## Generation", ""]
    lines.append(f"- seed: {seed}")

    if server_info:
        if server_info.model:
            lines.append(f"- acestep_model: {server_info.model}")
        if server_info.lm_model:
            lines.append(f"- acestep_lm_model: {server_info.lm_model}")

    try:
        version = importlib.metadata.version("songmaker")
    except importlib.metadata.PackageNotFoundError:
        version = "dev"
    lines.append(f"- songmaker_version: {version}")
    lines.append(f"- source: {source_path.name}")
    lines.append(f"- generated_at: {datetime.datetime.now().isoformat(timespec='seconds')}")

    return "\n".join(lines)


def append_scores_section(snapshot_path: Path, scores: SongScores) -> None:
    """Append a ## Scores section to an existing snapshot .md file."""
    score_dict = scores.to_dict()
    if not score_dict:
        return

    lines = ["## Scores", ""]
    for key, value in score_dict.items():
        lines.append(f"- {key}: {value}")

    text = snapshot_path.read_text(encoding="utf-8").rstrip()
    text += "\n\n" + "\n".join(lines) + "\n"
    snapshot_path.write_text(text, encoding="utf-8")
    log.info("Scores appended to %s", snapshot_path.name)


def _write_raw(
    paths: OutputPaths,
    source_text: str,
    ace_config: AceStepConfig,
    seed: int,
    server_info: ServerInfo | None,
) -> Path:
    """Fallback: write snapshot even if source has no frontmatter."""
    snapshot_path = paths.output_dir / f"{paths.versioned_name}.md"
    generation_section = _build_generation_section(seed, server_info, Path("unknown"))
    snapshot_path.write_text(source_text + "\n\n" + generation_section + "\n", encoding="utf-8")
    return snapshot_path
