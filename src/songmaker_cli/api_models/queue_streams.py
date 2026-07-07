"""Queue stream API models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QueueStreamTrackRequest(BaseModel):
    generation_id: str = Field(min_length=1, max_length=36)
    entry_id: str | None = Field(default=None, max_length=100)


class QueueStreamSnapshotRequest(BaseModel):
    tracks: list[QueueStreamTrackRequest] = Field(min_length=1, max_length=500)


class QueueStreamLibraryRequest(BaseModel):
    start_generation_id: str | None = Field(default=None, max_length=36)


class QueueStreamTrackResponse(BaseModel):
    key: str
    index: int
    entry_id: str | None
    generation_id: str
    song_id: str
    song_title: str
    artist: str
    generation_number: int
    mp3_path: str
    audio_url: str
    seed: int | None
    model_mode: str
    duration: float
    start_offset: float
    end_offset: float


class QueueStreamManifestResponse(BaseModel):
    snapshot_id: str
    stream_url: str
    expires_at: str
    total_duration: float
    tracks: list[QueueStreamTrackResponse]
    windowed: bool = False
