"""Parse song markdown and album YAML files into pydantic models."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator

from songmaker_cli.constants import DEFAULT_ARTIST
from songmaker_cli.errors import ValidationError

_ACE_STEP_FIELDS = frozenset({
    "bpm", "duration", "key", "time_signature", "language",
    "seed", "inference_steps", "guidance_scale", "shift",
    "think_mode", "lm_temperature", "infer_method",
})


class SongMeta(BaseModel):
    """Song metadata extracted from a markdown file's YAML frontmatter."""

    title: str = "Untitled"
    album: str = "unknown"
    track: str = ""
    genre: str = ""
    prompt: str = ""
    lyrics: str = ""
    status: str = ""
    source_path: Path = Path()
    generation_params: dict = {}

    @field_validator("track", mode="before")
    @classmethod
    def _coerce_track(cls, v: object) -> str:
        return str(v) if v is not None else ""


class AlbumMeta(BaseModel):
    """Album-level metadata from album.yaml."""

    title: str
    artist: str = DEFAULT_ARTIST
    subtitle: str = ""
    year: str = ""
    colors: dict[str, str] | None = None


def extract_lyrics(text: str) -> str | None:
    """Extract the ## Lyrics section from markdown text."""
    match = re.search(r"## Lyrics\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    return match.group(1).strip() if match else None


def parse_song_md(path: Path) -> SongMeta:
    """Parse a song .md file with YAML frontmatter + lyrics into SongMeta."""
    text = path.read_text(encoding="utf-8")

    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValidationError(f"No YAML frontmatter found in {path}")

    raw = yaml.safe_load(parts[1]) or {}

    body = parts[2]
    lyrics = extract_lyrics(body)
    if lyrics:
        raw["lyrics"] = lyrics

    raw.setdefault("title", path.stem)
    raw.setdefault("album", path.parent.parent.name)
    raw["source_path"] = path

    gen_params = {k: v for k, v in raw.items() if k in _ACE_STEP_FIELDS}

    meta_fields = {
        k: v for k, v in raw.items()
        if k in SongMeta.model_fields and k != "generation_params"
    }
    meta_fields["generation_params"] = gen_params

    return SongMeta(**meta_fields)


def strip_version_suffix(stem: str) -> str:
    """Strip '_v<N>' suffix from a track stem. E.g. '01_song_v3' -> '01_song'."""
    return re.sub(r"_v\d+$", "", stem)


def find_lyrics_md(stem: str, lyrics_dir: Path) -> Path | None:
    """Find a lyrics markdown file matching a track stem (with or without version)."""
    candidate = lyrics_dir / f"{stem}.md"
    if candidate.exists():
        return candidate
    base = strip_version_suffix(stem)
    candidate = lyrics_dir / f"{base}.md"
    if candidate.exists():
        return candidate
    return None


def parse_album_yaml(path: Path) -> AlbumMeta:
    """Parse album.yaml into AlbumMeta."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AlbumMeta(
        title=raw.get("title", path.parent.name.replace("_", " ").title()),
        artist=raw.get("artist", DEFAULT_ARTIST),
        subtitle=raw.get("subtitle", ""),
        year=str(raw.get("year", "")),
        colors=raw.get("colors"),
    )
