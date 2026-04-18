"""Pydantic models for MCP tool inputs and outputs.

Returning structured Pydantic models (rather than free-form dicts) means
the FastMCP layer auto-derives a JSON schema for each tool's output,
which the Claude client uses to interpret tool results.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from songmaker_cli.db.models import Album, Generation, Song, Version


class AlbumSummary(BaseModel):
    id: str
    title: str
    artist: str
    subtitle: str
    year: str
    song_count: int

    @classmethod
    def from_orm_with_count(cls, album: Album, song_count: int) -> AlbumSummary:
        return cls(
            id=album.id,
            title=album.title,
            artist=album.artist,
            subtitle=album.subtitle,
            year=album.year,
            song_count=song_count,
        )


class SongSummary(BaseModel):
    id: str
    title: str
    album_id: str
    album_title: str
    track_number: int
    vocal_language: str
    has_picked_generation: bool
    version_count: int
    generation_count: int

    @classmethod
    def from_orm(cls, song: Song) -> SongSummary:
        return cls(
            id=song.id,
            title=song.title,
            album_id=song.album_id,
            album_title=song.album.title if song.album else "",
            track_number=song.track_number,
            vocal_language=song.vocal_language,
            has_picked_generation=any(g.is_picked for g in song.generations),
            version_count=len(song.versions),
            generation_count=len(song.generations),
        )


class VersionSummary(BaseModel):
    id: str
    version_number: int
    lyrics: str
    prompt: str
    bpm: int
    key_scale: str
    audio_duration: int
    generation_count: int
    created_at: datetime

    @classmethod
    def from_orm(cls, version: Version) -> VersionSummary:
        return cls(
            id=version.id,
            version_number=version.version_number,
            lyrics=version.lyrics,
            prompt=version.prompt,
            bpm=version.bpm,
            key_scale=version.key_scale,
            audio_duration=version.audio_duration,
            generation_count=len(version.generations),
            created_at=version.created_at,
        )


class SongDetail(BaseModel):
    """Full view of a song — the 'current draft' state plus version/gen lists."""
    id: str
    title: str
    album_id: str
    album_title: str
    track_number: int
    vocal_language: str
    current_lyrics: str = Field(description="Lyrics on the latest version")
    current_prompt: str = Field(description="Style prompt on the latest version")
    current_bpm: int
    current_key_scale: str
    current_audio_duration: int
    latest_version_id: str | None
    versions: list[VersionSummary]
    generation_ids: list[str]
    picked_generation_id: str | None
    kept_generation_ids: list[str]

    @classmethod
    def from_orm(cls, song: Song) -> SongDetail:
        latest = song.latest_version
        picked = next((g for g in song.generations if g.is_picked), None)
        return cls(
            id=song.id,
            title=song.title,
            album_id=song.album_id,
            album_title=song.album.title if song.album else "",
            track_number=song.track_number,
            vocal_language=song.vocal_language,
            current_lyrics=latest.lyrics if latest else "",
            current_prompt=latest.prompt if latest else "",
            current_bpm=latest.bpm if latest else 0,
            current_key_scale=latest.key_scale if latest else "",
            current_audio_duration=latest.audio_duration if latest else 0,
            latest_version_id=latest.id if latest else None,
            versions=[VersionSummary.from_orm(v) for v in song.versions],
            generation_ids=[g.id for g in song.generations],
            picked_generation_id=picked.id if picked else None,
            kept_generation_ids=[g.id for g in song.generations if g.is_kept],
        )


class GenerationDetail(BaseModel):
    id: str
    song_id: str
    version_id: str | None
    generation_number: int
    seed: int | None
    model_mode: str
    status: str
    is_picked: bool
    is_kept: bool
    is_archived: bool
    whisper_text: str | None
    rating: float | None
    created_at: datetime
    scores: dict[str, float | None]

    @classmethod
    def from_orm(cls, gen: Generation) -> GenerationDetail:
        scores: dict[str, float | None] = {}
        for score in gen.scores:
            value = score.value
            if isinstance(value, dict) and "score" in value:
                scores[score.scorer] = value["score"]
            else:
                scores[score.scorer] = None
        return cls(
            id=gen.id,
            song_id=gen.song_id,
            version_id=gen.version_id,
            generation_number=gen.generation_number,
            seed=gen.seed,
            model_mode=gen.model_mode,
            status=gen.status,
            is_picked=gen.is_picked,
            is_kept=gen.is_kept,
            is_archived=gen.is_archived,
            whisper_text=gen.whisper_text,
            rating=gen.rating.rating if gen.rating else None,
            created_at=gen.created_at,
            scores=scores,
        )


class WriteResult(BaseModel):
    """Outcome of a write tool call."""
    ok: bool = True
    song_id: str
    message: str
    song: SongDetail
