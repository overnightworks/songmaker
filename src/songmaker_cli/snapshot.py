"""Read and write generation snapshot markdown files alongside MP3 output."""

from __future__ import annotations

import datetime
import importlib.metadata
import logging
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, TypedDict

import yaml

from acestep_engine.models import AceStepConfig, ServerInfo
from songmaker_cli.config import OutputPaths
from songmaker_cli.scoring.models import SongScores


class GenerationInfo(TypedDict, total=False):
    """Generation metadata from a sidecar snapshot .md."""

    seed: int
    acestep_model: str
    acestep_lm_model: str
    songmaker_version: str
    source: str
    generated_at: str
    bpm: int
    duration: int
    key: str
    guidance_scale: float
    inference_steps: int
    shift: float
    think_mode: bool
    lm_temperature: float
    infer_method: str


_GENERATION_KEYS = frozenset({
    "seed", "acestep_model", "acestep_lm_model", "songmaker_version",
    "source", "generated_at",
})

_FRONTMATTER_GEN_KEYS = frozenset({
    "bpm", "duration", "key", "guidance_scale", "inference_steps",
    "shift", "think_mode", "lm_temperature", "infer_method",
})

log = logging.getLogger(__name__)

_FIELD_REVERSE_MAPPING = {"vocal_language": "language"}

_SCORES_HEADER = "## Scores"


# ── Section helpers ──────────────────────────────────────────────────


def _split_at_scores(text: str) -> tuple[str, dict[str, object]]:
    """Split snapshot text into (before_scores, scores_dict).

    Returns the text before ## Scores (stripped) and a dict of parsed
    score key-value pairs. Returns empty dict if no ## Scores section.
    """
    match = re.search(r"## Scores\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if not match:
        return text.rstrip(), {}

    before = text[:match.start()].rstrip()
    scores: dict[str, object] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if line.startswith("- ") and ": " in line:
            key, _, value = line[2:].partition(": ")
            scores[key] = _coerce_value(value)

    return before, scores


def _format_scores_section(scores: dict[str, object]) -> str:
    """Format a scores dict as a ## Scores markdown section."""
    lines = [_SCORES_HEADER, ""]
    lines.extend(f"- {key}: {value}" for key, value in scores.items())
    return "\n".join(lines)


def _write_scores(snapshot_path: Path, before: str, scores: dict[str, object]) -> None:
    """Write a snapshot file with before-text + scores section."""
    text = before + "\n\n" + _format_scores_section(scores) + "\n"
    snapshot_path.write_text(text, encoding="utf-8")


# ── Snapshot writing ─────────────────────────────────────────────────


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
    lines.append(f"- generated_at: {datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}")

    return "\n".join(lines)


# ── Scores section read/write ────────────────────────────────────────


def append_scores_section(snapshot_path: Path, scores: SongScores) -> None:
    """Write a ## Scores section to a snapshot .md file.

    Idempotent — replaces an existing ## Scores section if present.
    Does nothing if all scorers returned None.
    """
    score_dict = scores.to_dict()
    if not score_dict:
        return

    text = snapshot_path.read_text(encoding="utf-8")
    before, _ = _split_at_scores(text)
    _write_scores(snapshot_path, before, score_dict)
    log.info("Scores written to %s", snapshot_path.name)


def save_rating(snapshot_path: Path, rating: int, notes: str = "") -> None:
    """Write user_rating (and optional notes) into the ## Scores section.

    Idempotent — replaces existing user_rating/user_notes if present.
    Creates ## Scores section if none exists.
    """
    text = snapshot_path.read_text(encoding="utf-8")
    before, existing = _split_at_scores(text)

    existing.pop("user_rating", None)
    existing.pop("user_notes", None)
    existing["user_rating"] = rating
    if notes:
        existing["user_notes"] = notes

    _write_scores(snapshot_path, before, existing)
    log.info("Rating saved: %s = %d stars", snapshot_path.name, rating)


def read_scores(snapshot_path: Path) -> dict[str, object] | None:
    """Read the ## Scores section from a snapshot .md file."""
    if not snapshot_path.exists():
        return None

    text = snapshot_path.read_text(encoding="utf-8")
    _, scores = _split_at_scores(text)
    return scores if scores else None


# ── Generation info reading ──────────────────────────────────────────


def read_generation_info(snapshot_path: Path) -> GenerationInfo | None:
    """Read generation metadata from a sidecar snapshot .md file."""
    if not snapshot_path.exists():
        return None

    text = snapshot_path.read_text(encoding="utf-8")
    info: GenerationInfo = {}

    parts = text.split("---", 2)
    if len(parts) >= 3:
        try:
            front = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            front = {}
        if isinstance(front, dict):
            for key in _FRONTMATTER_GEN_KEYS:
                if key in front:
                    info[key] = front[key]  # type: ignore[literal-required]

    gen_match = re.search(r"## Generation\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if gen_match:
        for line in gen_match.group(1).splitlines():
            line = line.strip()
            if line.startswith("- ") and ": " in line:
                key, _, value = line[2:].partition(": ")
                if key in _GENERATION_KEYS:
                    info[key] = _coerce_value(value)  # type: ignore[literal-required]

    return info if info else None


# ── Helpers ──────────────────────────────────────────────────────────


def _coerce_value(value: str) -> Any:
    """Try to parse a string value as int/float/bool."""
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


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
