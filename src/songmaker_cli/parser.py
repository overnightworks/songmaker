"""Song and album data models used across the songmaker engine."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel, Field, field_validator

from songmaker_cli.constants import DEFAULT_ARTIST

_ACE_STEP_FIELDS = frozenset({
    "bpm", "duration", "key", "time_signature", "language",
    "seed", "inference_steps", "guidance_scale", "shift",
    "think_mode", "lm_temperature", "infer_method",
})


class GenerationParams(TypedDict, total=False):
    bpm: int
    duration: int
    key: str
    time_signature: str
    language: str
    seed: int
    inference_steps: int
    guidance_scale: float
    shift: float
    think_mode: bool
    lm_temperature: float
    infer_method: str


class SongMeta(BaseModel):
    title: str = "Untitled"
    album: str = "unknown"
    track: str = Field(default="")
    genre: str = ""
    prompt: str = ""
    lyrics: str = ""
    status: str = ""
    source_path: Path = Path()
    generation_params: GenerationParams = Field(default_factory=dict)

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
