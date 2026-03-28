"""Song and album data models used across the songmaker engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from songmaker_cli.constants import DEFAULT_ARTIST


class SongMeta(BaseModel):
    title: str = "Untitled"
    album: str = "unknown"
    track: str = Field(default="")
    genre: str = ""
    prompt: str = ""
    lyrics: str = ""
    status: str = ""
    source_path: Path = Path()
    generation_params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("track", mode="before")
    @classmethod
    def _coerce_track(cls, v: object) -> str:
        return str(v) if v is not None else ""


class AlbumMeta(BaseModel):
    title: str
    artist: str = DEFAULT_ARTIST
    subtitle: str = ""
    year: str = ""
    colors: dict[str, str] | None = None
