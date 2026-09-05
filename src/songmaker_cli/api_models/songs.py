"""Song, album, version, and generation API models."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from songmaker_cli.api_models.fields import ComputedTimestamp
from songmaker_cli.api_models.generation_params import (
    BaseGenerationParams,
)
from songmaker_cli.api_models.whisper import (
    WhisperCue,
    generation_whisper_cues,
)
from songmaker_cli.constants import (
    COVER_VARIANT_CARD,
    COVER_VARIANT_DETAIL,
    COVER_VERSION_QUERY,
    MODEL_AVAILABLE_MODES,
)
from songmaker_cli.scoring.registry import VALID_SCORER_NAMES
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from songmaker_cli.db.models import Album, Generation, Song, Version


def generation_version_lyrics(gen: Generation) -> str | None:
    if not gen.version_id:
        return None
    version = gen.version
    if version is None:
        raise RuntimeError(
            f"Generation {gen.id} references version {gen.version_id} which is not loaded"
        )
    lyrics = version.lyrics
    if not lyrics:
        return None
    return lyrics


@dataclass(frozen=True)
class SharePickMedia:
    """Everything a listener needs to play one shared take: its generation,
    duration, lyrics, and the cues that make those lyrics follow playback —
    the same fields Now Playing reads from a generation payload.

    Null across all fields when there is no playable generation — same
    "no pick" honesty as `audio_url: null` on the surrounding response.
    """

    generation_id: str | None
    audio_duration: float | None
    lyrics: str | None
    whisper_cues: list[WhisperCue] | None


_NO_SHARE_PICK_MEDIA = SharePickMedia(
    generation_id=None, audio_duration=None, lyrics=None, whisper_cues=None,
)


def share_pick_media(gen: Generation | None) -> SharePickMedia:
    """The picked take's own measured length -- never the request parameter
    it was generated with (#258): a listener sees what the take actually
    plays for, not what it was asked to render."""
    if gen is None or not gen.mp3_path:
        return _NO_SHARE_PICK_MEDIA
    return SharePickMedia(
        generation_id=gen.id,
        audio_duration=gen.audio_duration_sec,
        lyrics=generation_version_lyrics(gen),
        whisper_cues=generation_whisper_cues(gen.whisper_cues),
    )


def _safe_json_dict(value: object, entity_type: str, entity_id: str) -> dict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    log.error(
        "Corrupted JSON dict in %s %s: expected dict, got %s",
        entity_type, entity_id, type(value).__name__,
    )
    return None


_VALID_REPAINT_MODES = frozenset({"conservative", "balanced", "aggressive"})
_VALID_MODEL_MODES = MODEL_AVAILABLE_MODES

ALBUM_YEAR_MIN = 1900
ALBUM_YEAR_MAX = 2100


GenerationParams = BaseGenerationParams


class AlbumCoverUrls(BaseModel):
    card: str
    detail: str


def album_cover_urls(album_id: str, cover_key: str) -> AlbumCoverUrls:
    return AlbumCoverUrls(
        card=(
            f"/api/albums/{album_id}/cover?variant={COVER_VARIANT_CARD}"
            f"&{COVER_VERSION_QUERY}={cover_key}"
        ),
        detail=(
            f"/api/albums/{album_id}/cover?variant={COVER_VARIANT_DETAIL}"
            f"&{COVER_VERSION_QUERY}={cover_key}"
        ),
    )


def public_album_cover_urls_at(path: str, cover_key: str) -> AlbumCoverUrls:
    return AlbumCoverUrls(
        card=(
            f"{path}?variant={COVER_VARIANT_CARD}"
            f"&{COVER_VERSION_QUERY}={cover_key}"
        ),
        detail=(
            f"{path}?variant={COVER_VARIANT_DETAIL}"
            f"&{COVER_VERSION_QUERY}={cover_key}"
        ),
    )


def public_album_cover_urls(slug: str, cover_key: str) -> AlbumCoverUrls:
    return public_album_cover_urls_at(f"/shared/{slug}/cover", cover_key)


class AlbumResponse(BaseModel):
    id: str
    title: str
    artist: str
    subtitle: str = ""
    year: str = ""
    colors: dict[str, str] = Field(default_factory=dict)
    song_count: int = 0
    picked_count: int = 0
    is_shared: bool = False
    share_slug: str | None = None
    cover: AlbumCoverUrls | None = None
    created_at: str
    is_archived: bool = False
    archived_at: str | None = None

    @classmethod
    def from_orm(cls, album: Album, *, song_count: int, picked_count: int = 0) -> AlbumResponse:
        cover = album_cover_urls(album.id, album.cover_key) if album.cover_key else None
        return cls(
            id=album.id,
            title=album.title,
            artist=album.artist,
            subtitle=album.subtitle,
            year=album.year,
            colors=album.colors or {},
            song_count=song_count,
            picked_count=picked_count,
            is_shared=album.is_shared,
            share_slug=album.share_slug,
            cover=cover,
            created_at=album.created_at.isoformat(),
            is_archived=album.is_archived,
            archived_at=album.archived_at.isoformat() if album.archived_at else None,
        )


class UnplayableSongSummary(BaseModel):
    """A song that will be silently absent from the public share page --
    no non-archived take carries audio to play."""

    id: str
    title: str


class ShareResponse(BaseModel):
    status: str = "ok"
    share_url: str
    share_slug: str
    songs_without_playable_take: list[UnplayableSongSummary] = Field(default_factory=list)


class SharedSongItem(BaseModel):
    id: str
    title: str
    track_number: int
    audio_url: str | None
    generation_id: str | None
    audio_duration: float | None
    lyrics: str | None
    whisper_cues: list[WhisperCue] | None


class SharedAlbumResponse(BaseModel):
    title: str
    artist: str
    subtitle: str
    year: str
    songs: list[SharedSongItem]
    cover: AlbumCoverUrls | None = None

    @classmethod
    def from_orm(
        cls,
        album: Album,
        *,
        songs: list[SharedSongItem],
        cover: AlbumCoverUrls | None = None,
    ) -> SharedAlbumResponse:
        return cls(
            title=album.title,
            artist=album.artist,
            subtitle=album.subtitle,
            year=album.year,
            songs=songs,
            cover=cover,
        )


class SharedSongResponse(BaseModel):
    title: str
    artist: str
    album_title: str
    audio_url: str | None
    generation_id: str | None
    audio_duration: float | None
    lyrics: str | None
    whisper_cues: list[WhisperCue] | None

    cover: AlbumCoverUrls | None = None
    album_cover: AlbumCoverUrls | None = None


class SharedGenerationResponse(BaseModel):
    title: str
    artist: str
    album_title: str
    generation_number: int
    seed: int | None
    audio_url: str | None
    generation_id: str | None
    audio_duration: float | None
    lyrics: str | None
    whisper_cues: list[WhisperCue] | None
    album_cover: AlbumCoverUrls | None = None


def generation_expiry(gen: Generation) -> datetime | None:
    """When cleanup will delete this generation, or None if it is safe.

    Picked and kept generations never expire. An archived generation is
    hard-deleted after the archive grace period; everything else is
    archived once the retention window since creation has passed.
    """
    if gen.is_picked or gen.is_kept:
        return None
    settings = get_settings()
    if gen.is_archived and gen.archived_at:
        return gen.archived_at + timedelta(days=settings.generation_hard_delete_days)
    return gen.created_at + timedelta(days=settings.generation_retention_days)


class GenerationResponse(BaseModel):
    id: str
    song_id: str
    version_id: str | None
    version_number: int | None
    generation_number: int
    mp3_path: str
    wav_path: str | None
    seed: int | None
    status: str
    is_archived: bool
    archived_at: str | None = None
    expires_at: ComputedTimestamp = None
    is_picked: bool
    is_kept: bool
    is_shared: bool = False
    share_slug: str | None = None
    model_mode: str
    src_generation_id: str | None = None
    src_generation_number: int | None = None
    src_generation_version_number: int | None = None
    whisper_text: str | None
    whisper_cues: list[WhisperCue] | None
    version_lyrics: str | None
    scores: dict | None
    generation_params: dict | None
    audio_duration_sec: float | None
    created_at: str

    @classmethod
    def from_orm(cls, gen: Generation) -> GenerationResponse:
        scores = _generation_scores(gen)
        generation_params = _safe_json_dict(
            gen.generation_params, "generation", gen.id,
        )

        archived_iso = gen.archived_at.isoformat() if gen.archived_at else None
        expiry = generation_expiry(gen)

        return cls(
            id=gen.id,
            song_id=gen.song_id,
            version_id=gen.version_id,
            version_number=gen.version.version_number if gen.version else None,
            generation_number=gen.generation_number,
            mp3_path=gen.mp3_path,
            wav_path=gen.wav_path,
            seed=gen.seed,
            status=gen.status,
            is_archived=gen.is_archived,
            archived_at=archived_iso,
            expires_at=expiry.isoformat() if expiry else None,
            is_picked=gen.is_picked,
            is_kept=gen.is_kept,
            is_shared=gen.is_shared,
            share_slug=gen.share_slug,
            model_mode=gen.model_mode,
            src_generation_id=gen.src_generation_id,
            src_generation_number=(
                gen.src_generation.generation_number
                if gen.src_generation else None
            ),
            src_generation_version_number=(
                gen.src_generation.version.version_number
                if gen.src_generation and gen.src_generation.version else None
            ),
            whisper_text=gen.whisper_text,
            whisper_cues=generation_whisper_cues(gen.whisper_cues),
            version_lyrics=generation_version_lyrics(gen),
            scores=scores if scores else None,
            generation_params=generation_params,
            audio_duration_sec=gen.audio_duration_sec,
            created_at=gen.created_at.isoformat(),
        )


def _generation_scores(gen: Generation) -> dict[str, object]:
    try:
        scores = _score_values(gen)
        _add_user_rating(scores, gen)
        return scores
    except (TypeError, AttributeError, KeyError):
        log.exception("Corrupted score data in generation %s", gen.id)
        return {}


def _score_values(gen: Generation) -> dict[str, object]:
    scores: dict[str, object] = {}
    for score in gen.scores:
        if not isinstance(score.value, dict):
            continue
        for key, value in score.value.items():
            if key in scores:
                log.warning("Duplicate score key '%s' in generation %s", key, gen.id)
            scores[key] = value
    return scores


def _add_user_rating(scores: dict[str, object], gen: Generation) -> None:
    if gen.rating is None:
        return
    scores["user_rating"] = gen.rating.rating
    scores["user_notes"] = gen.rating.notes


def song_cover_urls(song_id: str, cover_key: str) -> AlbumCoverUrls:
    return AlbumCoverUrls(
        card=(
            f"/api/songs/{song_id}/cover?variant={COVER_VARIANT_CARD}"
            f"&{COVER_VERSION_QUERY}={cover_key}"
        ),
        detail=(
            f"/api/songs/{song_id}/cover?variant={COVER_VARIANT_DETAIL}"
            f"&{COVER_VERSION_QUERY}={cover_key}"
        ),
    )


def public_song_cover_urls(slug: str, cover_key: str) -> AlbumCoverUrls:
    return AlbumCoverUrls(
        card=(
            f"/shared/song/{slug}/cover?variant={COVER_VARIANT_CARD}"
            f"&{COVER_VERSION_QUERY}={cover_key}"
        ),
        detail=(
            f"/shared/song/{slug}/cover?variant={COVER_VARIANT_DETAIL}"
            f"&{COVER_VERSION_QUERY}={cover_key}"
        ),
    )


class VersionResponse(BaseModel):
    id: str
    version_number: int
    lyrics: str
    prompt: str
    bpm: int
    audio_duration: int
    key_scale: str
    generation_params: dict | None
    created_at: str

    @classmethod
    def from_orm(cls, ver: Version) -> VersionResponse:
        generation_params = _safe_json_dict(ver.generation_params, "version", ver.id)
        return cls(
            id=ver.id,
            version_number=ver.version_number,
            lyrics=ver.lyrics,
            prompt=ver.prompt,
            bpm=ver.bpm,
            audio_duration=ver.audio_duration,
            key_scale=ver.key_scale,
            generation_params=generation_params,
            created_at=ver.created_at.isoformat(),
        )


class SongSummaryResponse(BaseModel):
    id: str
    slug: str
    title: str
    album_id: str
    album_title: str = ""
    artist: str = ""
    track_number: int
    vocal_language: str = ""
    lyrics: str = ""
    prompt: str = ""
    bpm: int | None = None
    audio_duration: int | None = None
    key_scale: str | None = None
    generation_params: dict | None = None
    version_count: int = 0
    generation_count: int = 0
    is_shared: bool = False
    share_slug: str | None = None
    best_scores: dict | None = None
    best_rating: float | None = None
    cover: AlbumCoverUrls | None = None
    created_at: str

    @classmethod
    def from_orm(cls, song: Song, *, generation_count: int) -> SongSummaryResponse:
        ver = song.latest_version
        generation_params = (
            _safe_json_dict(ver.generation_params, "version", ver.id)
            if ver else None
        )
        cover = song_cover_urls(song.id, song.cover_key) if song.cover_key else None
        return cls(
            id=song.id,
            slug=song.slug,
            title=song.title,
            album_id=song.album_id,
            album_title=song.album.title if song.album else "",
            artist=song.album.artist if song.album else "",
            track_number=song.track_number,
            vocal_language=song.vocal_language,
            lyrics=ver.lyrics if ver else "",
            prompt=ver.prompt if ver else "",
            bpm=ver.bpm if ver else None,
            audio_duration=ver.audio_duration if ver else None,
            key_scale=ver.key_scale if ver else None,
            generation_params=generation_params,
            version_count=len(song.versions),
            generation_count=generation_count,
            is_shared=song.is_shared,
            share_slug=song.share_slug,
            cover=cover,
            created_at=song.created_at.isoformat(),
        )


class SongResponse(SongSummaryResponse):
    generations: list[GenerationResponse] = Field(default_factory=list)

    @classmethod
    def from_orm(cls, song: Song) -> SongResponse:
        # song.generations is always eager-loaded on this path (get_song(),
        # list_songs(light=False)), unlike the light SongSummaryResponse
        # list path — so counting it here costs no extra query.
        base = SongSummaryResponse.from_orm(song, generation_count=len(song.generations))

        best_gen = _best_generation(song.generations)
        best_scores: dict[str, object] | None = None
        if best_gen:
            best_scores = {}
            for s in best_gen.scores:
                if isinstance(s.value, dict):
                    best_scores.update(s.value)

        exclude = {"best_scores", "best_rating"}
        return cls(
            **{k: v for k, v in base.model_dump().items() if k not in exclude},
            best_scores=best_scores if best_scores else None,
            best_rating=best_gen.rating.rating if best_gen and best_gen.rating else None,
            generations=[GenerationResponse.from_orm(g) for g in song.generations],
        )


def _audiobox_quality(generation: Generation) -> float | None:
    for score in generation.scores:
        if isinstance(score.value, dict) and "audiobox_quality" in score.value:
            return score.value["audiobox_quality"]
    return None


def _best_generation(generations: list[Generation]) -> Generation | None:
    active = [g for g in generations if not g.is_archived]
    rated = [g for g in active if g.rating]
    if rated:
        return max(rated, key=lambda g: g.rating.rating)
    scored = [g for g in active if _audiobox_quality(g) is not None]
    if scored:
        return max(scored, key=_audiobox_quality)
    return active[0] if active else None


class AlbumCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field("", max_length=200)


class AlbumUpdateRequest(BaseModel):
    """Partial update for album metadata — title, subtitle, and year.

    A field absent from the request body is left unchanged. An explicit
    empty subtitle clears it. Title, if present, must be non-blank.
    """

    title: str | None = Field(None, max_length=200)
    subtitle: str | None = Field(None, max_length=400)
    year: int | None = Field(None, ge=ALBUM_YEAR_MIN, le=ALBUM_YEAR_MAX)


class SongCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    album_id: str = Field(max_length=64)
    lyrics: str = Field("", max_length=50_000)
    prompt: str = Field("", max_length=5_000)
    bpm: int = Field(0, ge=0, le=999)
    audio_duration: int = Field(180, ge=0, le=600)
    key_scale: str = Field("", max_length=10)
    vocal_language: str = Field("", max_length=10)
    generation_params: GenerationParams | None = None


class SongUpdateRequest(BaseModel):
    lyrics: str | None = Field(None, max_length=50_000)
    prompt: str | None = Field(None, max_length=5_000)
    bpm: int | None = Field(None, ge=0, le=999)
    audio_duration: int | None = Field(None, ge=0, le=600)
    key_scale: str | None = Field(None, max_length=10)
    generation_params: GenerationParams | None = None


class SongMoveRequest(BaseModel):
    album_id: str = Field(max_length=64)


class TitleUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class GenerateRequest(BaseModel):
    count: int = Field(1, ge=1, le=10)
    model: str
    version_id: str | None = None
    seed: int | None = Field(None, ge=-1)

    @field_validator("model")
    @classmethod
    def _validate_model(cls, v: str) -> str:
        if v not in _VALID_MODEL_MODES:
            msg = f"model must be one of {sorted(_VALID_MODEL_MODES)}"
            raise ValueError(msg)
        return v


class RepaintRequest(BaseModel):
    src_generation_id: str = Field(max_length=36)
    repainting_start: float = Field(ge=0.0, le=1.0)
    repainting_end: float = Field(ge=0.0, le=1.0)
    lyrics: str | None = Field(None, max_length=50_000)
    prompt: str | None = Field(None, max_length=5_000)
    version_id: str | None = Field(None, max_length=36)
    count: int = Field(1, ge=1, le=10)
    model: str
    seed: int | None = Field(None, ge=-1)
    repaint_mode: str | None = Field(None, max_length=20)
    repaint_strength: float | None = Field(None, ge=0, le=1)
    repaint_latent_crossfade_frames: int | None = Field(None, ge=0)
    repaint_wav_crossfade_sec: float | None = Field(None, ge=0)

    @field_validator("model")
    @classmethod
    def _validate_model(cls, v: str) -> str:
        if v not in _VALID_MODEL_MODES:
            msg = f"model must be one of {sorted(_VALID_MODEL_MODES)}"
            raise ValueError(msg)
        return v

    @field_validator("repaint_mode")
    @classmethod
    def _validate_repaint_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_REPAINT_MODES:
            msg = f"repaint_mode must be one of {sorted(_VALID_REPAINT_MODES)}"
            raise ValueError(msg)
        return v


class CoverRequest(BaseModel):
    src_generation_id: str = Field(max_length=36)
    audio_cover_strength: float = Field(0.8, ge=0.0, le=1.0)
    cover_noise_strength: float | None = Field(None, ge=0, le=1)
    lyrics: str | None = Field(None, max_length=50_000)
    prompt: str | None = Field(None, max_length=5_000)
    version_id: str | None = Field(None, max_length=36)
    count: int = Field(1, ge=1, le=10)
    model: str
    seed: int | None = Field(None, ge=-1)

    @field_validator("model")
    @classmethod
    def _validate_model(cls, v: str) -> str:
        if v not in _VALID_MODEL_MODES:
            msg = f"model must be one of {sorted(_VALID_MODEL_MODES)}"
            raise ValueError(msg)
        return v


class ScoreRequest(BaseModel):
    scorers: list[str] | None = Field(None, max_length=20)

    @field_validator("scorers")
    @classmethod
    def validate_scorer_items(cls, v: list[str] | None) -> list[str] | None:
        if v:
            invalid = set(v) - VALID_SCORER_NAMES
            if invalid:
                msg = f"Unknown scorers: {', '.join(sorted(invalid))}"
                raise ValueError(msg)
        return v


class ScorerSchemaItem(BaseModel):
    name: str
    output_keys: list[str]
    needs_audio: bool
    device: str
    host: str


class ScoringSchemaResponse(BaseModel):
    scorers: list[ScorerSchemaItem]

    @classmethod
    def from_registry(cls) -> "ScoringSchemaResponse":
        from songmaker_cli.scoring.registry import SCORERS

        return cls(
            scorers=[
                ScorerSchemaItem(
                    name=spec.name,
                    output_keys=list(spec.output_keys),
                    needs_audio=spec.needs_audio,
                    device=spec.device,
                    host=spec.host.value,
                )
                for spec in SCORERS.values()
            ],
        )


class RateRequest(BaseModel):
    rating: float = Field(ge=0, le=100)
    notes: str = Field("", max_length=2_000)


class BulkDeleteRequest(BaseModel):
    generation_ids: list[str] = Field(max_length=100)


class BulkDeleteResponse(BaseModel):
    deleted: int
