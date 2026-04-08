"""Playlist API request and response models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from songmaker_cli.db.models import Playlist, PlaylistEntry


class PlaylistEntryResponse(BaseModel):
    id: str
    position: int
    generation_id: str
    song_title: str
    album_title: str
    artist: str
    generation_number: int
    mp3_path: str
    seed: int | None
    model_mode: str

    @classmethod
    def from_orm(cls, entry: PlaylistEntry) -> PlaylistEntryResponse:
        gen = entry.generation
        song = gen.song
        album = song.album if song else None
        return cls(
            id=entry.id,
            position=entry.position,
            generation_id=gen.id,
            song_title=song.title if song else "",
            album_title=album.title if album else "",
            artist=album.artist if album else "",
            generation_number=gen.generation_number,
            mp3_path=gen.mp3_path,
            seed=gen.seed,
            model_mode=gen.model_mode,
        )


class PlaylistResponse(BaseModel):
    id: str
    title: str
    entry_count: int
    is_shared: bool = False
    share_slug: str | None = None
    created_at: str | None = None

    @classmethod
    def from_orm(cls, playlist: Playlist) -> PlaylistResponse:
        return cls(
            id=playlist.id,
            title=playlist.title,
            entry_count=len(playlist.entries) if playlist.entries else 0,
            is_shared=playlist.is_shared,
            share_slug=playlist.share_slug,
            created_at=playlist.created_at.isoformat() if playlist.created_at else None,
        )


class PlaylistDetailResponse(PlaylistResponse):
    entries: list[PlaylistEntryResponse] = Field(default_factory=list)

    @classmethod
    def from_orm(cls, playlist: Playlist) -> PlaylistDetailResponse:
        base = PlaylistResponse.from_orm(playlist)
        entries = [
            PlaylistEntryResponse.from_orm(e)
            for e in sorted(playlist.entries, key=lambda e: e.position)
            if e.generation is not None
        ]
        return cls(
            **base.model_dump(),
            entries=entries,
        )


class PlaylistCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class PlaylistUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class AddGenerationToPlaylistRequest(BaseModel):
    generation_id: str


class AddSongToPlaylistRequest(BaseModel):
    song_id: str


class AddAlbumToPlaylistRequest(BaseModel):
    album_id: str


class ReorderPlaylistEntryRequest(BaseModel):
    new_position: int = Field(ge=0)


class SharedPlaylistEntryResponse(BaseModel):
    song_title: str
    artist: str
    generation_number: int
    audio_url: str | None


class SharedPlaylistResponse(BaseModel):
    title: str
    entries: list[SharedPlaylistEntryResponse]
