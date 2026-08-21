"""Queue stream API models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

LibraryTakePool = Literal["mix", "picks", "keeps", "all"]
DEFAULT_LIBRARY_TAKE_POOL: LibraryTakePool = "mix"


class QueueStreamTrackRequest(BaseModel):
    generation_id: str = Field(min_length=1, max_length=36)
    entry_id: str | None = Field(default=None, max_length=100)


class QueueStreamSnapshotRequest(BaseModel):
    tracks: list[QueueStreamTrackRequest] = Field(min_length=1, max_length=500)


class QueueStreamLibraryRequest(BaseModel):
    start_generation_id: str | None = Field(default=None, max_length=36)
    shuffle: bool = False
    pool: LibraryTakePool = DEFAULT_LIBRARY_TAKE_POOL


class QueueStreamTrackResponse(BaseModel):
    key: str
    index: int
    entry_id: str | None
    generation_id: str
    song_id: str
    song_title: str
    artist: str
    album_title: str
    lyrics: str | None
    generation_number: int
    mp3_path: str
    audio_url: str
    seed: int | None
    model_mode: str
    duration: float
    start_offset: float
    end_offset: float


class QueueStreamSkipResponse(BaseModel):
    song_id: str
    generation_id: str
    reason: Literal["missing_path", "missing_file", "unreadable_file"]


class QueueStreamManifestResponse(BaseModel):
    snapshot_id: str
    stream_url: str
    expires_at: str
    total_duration: float
    tracks: list[QueueStreamTrackResponse]
    windowed: bool = False
    skipped: list[QueueStreamSkipResponse] = Field(default_factory=list)
    skipped_complete: bool = True


class QueueStreamPinResponse(BaseModel):
    snapshot_id: str
    pinned: bool
    pinned_at: str | None
