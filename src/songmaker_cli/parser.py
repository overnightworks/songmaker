"""Song and album data models used across the songmaker engine."""

from __future__ import annotations

from pydantic import BaseModel, Field

from songmaker_cli.constants import DEFAULT_ARTIST
from songmaker_cli.generation_params import BaseGenerationParams


class SongMeta(BaseModel):
    title: str = "Untitled"
    track: str = Field(default="")
    prompt: str = ""
    lyrics: str = ""
    bpm: int = 0
    audio_duration: int = 0
    key_scale: str = ""
    vocal_language: str = ""
    generation_params: BaseGenerationParams = Field(default_factory=BaseGenerationParams)


class AlbumMeta(BaseModel):
    title: str
    artist: str = DEFAULT_ARTIST
