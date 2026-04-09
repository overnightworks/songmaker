"""Song and album data models used across the songmaker engine."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from songmaker_cli.api_models.generation_params import BaseGenerationParams
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
    bpm: int = 0
    audio_duration: int = 0
    key_scale: str = ""
    vocal_language: str = ""
    generation_params: BaseGenerationParams = Field(default_factory=BaseGenerationParams)

    @field_validator("track", mode="before")
    @classmethod
    def _coerce_track(cls, v: object) -> str:
        return str(v) if v is not None else ""

    @field_validator("generation_params", mode="before")
    @classmethod
    def _coerce_generation_params(cls, v: object) -> object:
        if v is None:
            return BaseGenerationParams()
        if isinstance(v, dict):
            return BaseGenerationParams.model_validate(v)
        return v


class AlbumMeta(BaseModel):
    title: str
    artist: str = DEFAULT_ARTIST
    subtitle: str = ""
    year: str = ""
    colors: dict[str, str] | None = None
