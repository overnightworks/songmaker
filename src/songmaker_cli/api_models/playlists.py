"""Playlist API request and response models."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from songmaker_cli.api_models.songs import (
    AlbumCoverUrls,
    album_cover_urls,
    generation_version_lyrics,
)
from songmaker_cli.api_models.whisper import WhisperCue

if TYPE_CHECKING:
    from songmaker_cli.db.models import Playlist, PlaylistEntry

log = logging.getLogger(__name__)


def _playlist_entries(playlist: Playlist) -> list[PlaylistEntry]:
    """Return playlist.entries, logging an ORM warning if the relationship
    is None (which should never happen — SQLAlchemy returns an empty list
    for an unfilled one-to-many, never ``None``)."""
    entries = playlist.entries
    if entries is None:
        log.warning(
            "Playlist %s has entries=None — ORM mapping bug, treating as empty",
            playlist.id,
        )
        return []
    return entries


class PlaylistEntryResponse(BaseModel):
    id: str
    position: int
    generation_id: str
    song_id: str
    song_title: str
    album_title: str
    artist: str
    generation_number: int
    version_number: int | None
    is_picked: bool
    audio_duration: float | None
    mp3_path: str
    seed: int | None
    model_mode: str
    lyrics: str | None

    @classmethod
    def from_orm(cls, entry: PlaylistEntry) -> PlaylistEntryResponse:
        gen = entry.generation
        song = gen.song
        album = song.album if song else None
        return cls(
            id=entry.id,
            position=entry.position,
            generation_id=gen.id,
            song_id=song.id if song else "",
            song_title=song.title if song else "",
            album_title=album.title if album else "",
            artist=album.artist if album else "",
            generation_number=gen.generation_number,
            version_number=gen.version.version_number if gen.version else None,
            is_picked=gen.is_picked,
            audio_duration=gen.audio_duration_sec,
            mp3_path=gen.mp3_path,
            seed=gen.seed,
            model_mode=gen.model_mode,
            lyrics=generation_version_lyrics(gen),
        )


class PlaylistResponse(BaseModel):
    id: str
    title: str
    slug: str
    entry_count: int
    is_shared: bool = False
    share_slug: str | None = None
    album_covers: list[AlbumCoverUrls] = Field(default_factory=list)
    created_at: str

    @classmethod
    def from_orm(cls, playlist: Playlist) -> PlaylistResponse:
        live_entries = [
            e for e in _playlist_entries(playlist)
            if e.generation is not None and e.generation.song is not None
        ]
        album_covers: list[AlbumCoverUrls] = []
        covered_album_ids: set[str] = set()
        for entry in live_entries:
            album = entry.generation.song.album
            if album is None or album.cover_key is None or album.id in covered_album_ids:
                continue
            covered_album_ids.add(album.id)
            album_covers.append(album_cover_urls(album.id, album.cover_key))
            if len(album_covers) == 4:
                break
        return cls(
            id=playlist.id,
            title=playlist.title,
            slug=playlist.slug,
            entry_count=len(live_entries),
            is_shared=playlist.is_shared,
            share_slug=playlist.share_slug,
            album_covers=album_covers,
            created_at=playlist.created_at.isoformat(),
        )


class PlaylistDetailResponse(PlaylistResponse):
    entries: list[PlaylistEntryResponse] = Field(default_factory=list)

    @classmethod
    def from_orm(cls, playlist: Playlist) -> PlaylistDetailResponse:
        base = PlaylistResponse.from_orm(playlist)
        entries = [
            PlaylistEntryResponse.from_orm(e)
            for e in sorted(_playlist_entries(playlist), key=lambda e: e.position)
            if e.generation is not None and e.generation.song is not None
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


class PlaylistAlbumSkipResponse(BaseModel):
    song_id: str
    title: str
    reason: str


class AddAlbumToPlaylistResponse(BaseModel):
    added_count: int
    skipped: list[PlaylistAlbumSkipResponse]


class ReorderPlaylistEntryRequest(BaseModel):
    new_position: int = Field(ge=0)


class SharedPlaylistEntryResponse(BaseModel):
    entry_id: str
    song_title: str
    artist: str
    generation_number: int
    audio_url: str | None
    generation_id: str | None
    audio_duration: float | None
    lyrics: str | None
    whisper_cues: list[WhisperCue] | None


class SharedPlaylistResponse(BaseModel):
    title: str
    entries: list[SharedPlaylistEntryResponse]
