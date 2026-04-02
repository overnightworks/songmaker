"""Song, album, version, and generation API models."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from songmaker_cli.config import get_builtin_defaults

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from songmaker_cli.db.models import Generation, Song, Version


_GEN_PARAM_MAX_STRING_LENGTH = 2000


def _safe_json_dict(
    value: object, entity_type: str, entity_id: str,
) -> dict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    log.warning("Corrupted JSON dict in %s %s", entity_type, entity_id)
    return None


_VALID_INFER_METHODS = frozenset({"ode", "sde"})
_VALID_THINK_MODES = frozenset({"deep", "off", ""})
_VALID_MODEL_MODES = frozenset(get_builtin_defaults().keys())

VALID_SCORER_NAMES = frozenset({
    "text_accuracy", "lyrical_coherence", "emotional_dynamics",
    "audiobox", "bpm_accuracy", "silence", "spectral_quality",
})


class GenerationParams(BaseModel):
    model_config = {"extra": "forbid"}

    inference_steps: int | None = Field(None, ge=1, le=200)
    guidance_scale: float | None = Field(None, ge=0, le=50)
    shift: float | None = Field(None, ge=0, le=100)
    think_mode: str | None = Field(None, max_length=10)
    lm_temperature: float | None = Field(None, ge=0, le=5)
    lm_top_k: int | None = Field(None, ge=0, le=1000)
    lm_top_p: float | None = Field(None, ge=0, le=1)
    lm_cfg_scale: float | None = Field(None, ge=0, le=50)
    lm_negative_prompt: str | None = Field(None, max_length=_GEN_PARAM_MAX_STRING_LENGTH)
    infer_method: str | None = Field(None, max_length=10)
    batch_size: int | None = Field(None, ge=1, le=8)

    @field_validator("infer_method")
    @classmethod
    def _validate_infer_method(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_INFER_METHODS:
            msg = f"infer_method must be one of {sorted(_VALID_INFER_METHODS)}"
            raise ValueError(msg)
        return v

    @field_validator("think_mode")
    @classmethod
    def _validate_think_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_THINK_MODES:
            msg = f"think_mode must be one of {sorted(_VALID_THINK_MODES)}"
            raise ValueError(msg)
        return v

    def to_dict(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class StoredGenerationParams(GenerationParams):
    seed: int | None = None
    acestep_model: str | None = None
    bpm: int | None = None
    duration: int | None = None
    key: str | None = None


class AlbumResponse(BaseModel):
    id: str
    title: str
    artist: str
    subtitle: str = ""
    year: str = ""
    colors: dict[str, str] = Field(default_factory=dict)
    song_count: int = 0
    is_shared: bool = False
    share_slug: str | None = None

    @classmethod
    def from_orm(cls, album) -> AlbumResponse:
        return cls(
            id=album.id,
            title=album.title,
            artist=album.artist,
            subtitle=album.subtitle,
            year=album.year,
            colors=album.colors or {},
            song_count=len(album.songs) if album.songs else 0,
            is_shared=album.is_shared,
            share_slug=album.share_slug,
        )


class ShareResponse(BaseModel):
    status: str = "ok"
    share_url: str
    share_slug: str


class SharedSongItem(BaseModel):
    title: str
    track_number: int
    audio_url: str | None


class SharedAlbumResponse(BaseModel):
    title: str
    artist: str
    subtitle: str
    year: str
    songs: list[SharedSongItem]


class SharedSongResponse(BaseModel):
    title: str
    artist: str
    album_title: str
    audio_url: str | None


class SharedGenerationResponse(BaseModel):
    title: str
    artist: str
    album_title: str
    generation_number: int
    seed: int | None
    audio_url: str | None


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
    is_picked: bool
    is_kept: bool
    is_shared: bool = False
    share_slug: str | None = None
    model_mode: str | None = None
    whisper_text: str | None
    scores: dict | None
    generation_params: dict | None
    created_at: str | None

    @classmethod
    def from_orm(cls, gen: Generation) -> GenerationResponse:
        scores: dict[str, object] = {}
        try:
            for score in gen.scores:
                if isinstance(score.value, dict):
                    for key, value in score.value.items():
                        if key in scores:
                            log.warning(
                                "Duplicate score key '%s' in generation %s", key, gen.id,
                            )
                        scores[key] = value
            if gen.rating:
                scores["user_rating"] = gen.rating.rating
                scores["user_notes"] = gen.rating.notes
        except (TypeError, AttributeError, KeyError):
            log.warning("Corrupted score data in generation %s", gen.id)
            scores = {}

        generation_params = _safe_json_dict(
            gen.generation_params, "generation", gen.id,
        )

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
            is_picked=gen.is_picked,
            is_kept=gen.is_kept,
            is_shared=gen.is_shared,
            share_slug=gen.share_slug,
            model_mode=gen.model_mode,
            whisper_text=gen.whisper_text,
            scores=scores if scores else None,
            generation_params=generation_params,
            created_at=gen.created_at.isoformat() if gen.created_at else None,
        )


class VersionResponse(BaseModel):
    id: str
    version_number: int
    lyrics: str
    prompt: str
    bpm: int
    duration: int
    key: str
    generation_params: dict | None
    created_at: str | None

    @classmethod
    def from_orm(cls, ver: Version) -> VersionResponse:
        generation_params = _safe_json_dict(ver.generation_params, "version", ver.id)
        return cls(
            id=ver.id,
            version_number=ver.version_number,
            lyrics=ver.lyrics,
            prompt=ver.prompt,
            bpm=ver.bpm,
            duration=ver.duration,
            key=ver.key,
            generation_params=generation_params,
            created_at=ver.created_at.isoformat() if ver.created_at else None,
        )


class SongSummaryResponse(BaseModel):
    id: str
    title: str
    album_id: str
    album_title: str = ""
    artist: str = ""
    track_number: int
    language: str = ""
    lyrics: str = ""
    prompt: str = ""
    bpm: int | None = None
    duration: int | None = None
    key: str = ""
    generation_params: dict | None = None
    version_count: int = 0
    generation_count: int = 0
    is_shared: bool = False
    share_slug: str | None = None
    best_scores: dict | None = None
    best_rating: float | None = None
    created_at: str | None = None

    @classmethod
    def from_orm(cls, song: Song) -> SongSummaryResponse:
        ver = song.latest_version
        generation_params = (
            _safe_json_dict(ver.generation_params, "version", ver.id)
            if ver else None
        )
        return cls(
            id=song.id,
            title=song.title,
            album_id=song.album_id,
            album_title=song.album.title if song.album else "",
            artist=song.album.artist if song.album else "",
            track_number=song.track_number,
            language=song.language,
            lyrics=ver.lyrics if ver else "",
            prompt=ver.prompt if ver else "",
            bpm=ver.bpm if ver else None,
            duration=ver.duration if ver else None,
            key=ver.key if ver else "",
            generation_params=generation_params,
            version_count=len(song.versions),
            generation_count=len(song.generations),
            is_shared=song.is_shared,
            share_slug=song.share_slug,
            created_at=song.created_at.isoformat() if song.created_at else None,
        )


class SongResponse(SongSummaryResponse):
    generations: list[GenerationResponse] = Field(default_factory=list)

    @classmethod
    def from_orm(cls, song: Song) -> SongResponse:
        base = SongSummaryResponse.from_orm(song)

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


def _best_generation(generations: list) -> object | None:
    rated = [g for g in generations if g.rating and not g.is_archived]
    if rated:
        return max(rated, key=lambda g: g.rating.rating)
    active = [g for g in generations if not g.is_archived]
    return active[0] if active else None


class AlbumCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field("", max_length=200)


class SongCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    album_id: str = Field(max_length=64)
    lyrics: str = Field("", max_length=50_000)
    prompt: str = Field("", max_length=5_000)
    bpm: int = Field(0, ge=0, le=999)
    duration: int = Field(180, ge=1, le=600)
    key: str = Field("", max_length=10)
    language: str = Field("", max_length=10)
    generation_params: GenerationParams | None = None


class SongUpdateRequest(BaseModel):
    lyrics: str | None = Field(None, max_length=50_000)
    prompt: str | None = Field(None, max_length=5_000)
    bpm: int | None = Field(None, ge=0, le=999)
    duration: int | None = Field(None, ge=1, le=600)
    key: str | None = Field(None, max_length=10)
    generation_params: GenerationParams | None = None


class SongMoveRequest(BaseModel):
    album_id: str = Field(max_length=64)


class GenerateRequest(BaseModel):
    count: int = Field(1, ge=1, le=10)
    model: str | None = None
    version_id: str | None = None
    seed: int | None = Field(None, ge=-1)

    @field_validator("model")
    @classmethod
    def _validate_model(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_MODEL_MODES:
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


class RateRequest(BaseModel):
    rating: float = Field(ge=0, le=100)
    notes: str = Field("", max_length=2_000)
