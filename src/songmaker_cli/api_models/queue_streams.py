"""Queue stream API models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from songmaker_cli.api_models.songs import generation_version_lyrics

if TYPE_CHECKING:
    from songmaker_cli.db.models import Generation

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


class LibraryPoolTakeResponse(BaseModel):
    generation_id: str
    song_id: str
    song_title: str
    artist: str
    album_title: str
    lyrics: str | None
    generation_number: int
    mp3_path: str
    seed: int | None
    model_mode: str
    is_picked: bool
    is_kept: bool

    @classmethod
    def from_orm(cls, generation: Generation) -> LibraryPoolTakeResponse:
        song = generation.song
        if song is None:
            raise ValueError(f"Generation {generation.id} has no song")
        album = song.album
        if album is None:
            raise ValueError(f"Song {song.id} has no album")
        if not generation.mp3_path:
            raise ValueError(f"Generation {generation.id} has no audio path")
        return cls(
            generation_id=generation.id,
            song_id=song.id,
            song_title=song.title,
            artist=album.artist,
            album_title=album.title,
            lyrics=generation_version_lyrics(generation),
            generation_number=generation.generation_number,
            mp3_path=generation.mp3_path,
            seed=generation.seed,
            model_mode=generation.model_mode,
            is_picked=bool(generation.is_picked),
            is_kept=bool(generation.is_kept),
        )


class LibraryPoolQueueResponse(BaseModel):
    pool: LibraryTakePool
    takes: list[LibraryPoolTakeResponse]
    skipped: list[QueueStreamSkipResponse] = Field(default_factory=list)
    skipped_complete: bool = True

    @classmethod
    def from_orm(
        cls,
        *,
        pool: LibraryTakePool,
        generations: list[Generation],
        skipped: list[QueueStreamSkipResponse],
        skipped_complete: bool,
    ) -> LibraryPoolQueueResponse:
        return cls(
            pool=pool,
            takes=[LibraryPoolTakeResponse.from_orm(generation) for generation in generations],
            skipped=skipped,
            skipped_complete=skipped_complete,
        )


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
