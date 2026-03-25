"""Pydantic models for API requests and responses.

These define the exact contract between backend and frontend.
FastAPI auto-generates OpenAPI docs from these models.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from songmaker_cli.auth import check_password_strength

if TYPE_CHECKING:
    from songmaker_cli.db.models import (
        Album,
        AuditLog,
        Generation,
        Job,
        LoginAttempt,
        Song,
        User,
        UserSession,
        Version,
    )


# ── Album ───────────────────────────────────────────────────────────


class AlbumResponse(BaseModel):
    id: str
    title: str
    artist: str
    subtitle: str = ""
    year: str = ""
    colors: dict[str, str] = Field(default_factory=dict)
    song_count: int = 0

    @classmethod
    def from_orm(cls, album: Album) -> AlbumResponse:
        return cls(
            id=album.id,
            title=album.title,
            artist=album.artist,
            subtitle=album.subtitle,
            year=album.year,
            colors=album.colors or {},
            song_count=len(album.songs) if album.songs else 0,
        )


# ── Generation ──────────────────────────────────────────────────────


class GenerationResponse(BaseModel):
    id: str
    song_id: str
    version_id: str | None
    version_number: int | None
    generation_number: int
    mp3_path: str
    seed: int | None
    status: str
    is_archived: bool
    is_picked: bool
    whisper_text: str | None
    scores: dict | None
    generation_params: dict | None
    created_at: str | None

    @classmethod
    def from_orm(cls, gen: Generation) -> GenerationResponse:
        scores: dict[str, object] = {}
        for score in gen.scores:
            if isinstance(score.value, dict):
                scores.update(score.value)
        if gen.rating:
            scores["user_rating"] = gen.rating.rating
            scores["user_notes"] = gen.rating.notes

        return cls(
            id=gen.id,
            song_id=gen.song_id,
            version_id=gen.version_id,
            version_number=gen.version.version_number if gen.version else None,
            generation_number=gen.generation_number,
            mp3_path=gen.mp3_path,
            seed=gen.seed,
            status=gen.status,
            is_archived=gen.is_archived,
            is_picked=gen.is_picked,
            whisper_text=gen.whisper_text,
            scores=scores if scores else None,
            generation_params=gen.generation_params,
            created_at=gen.created_at.isoformat() if gen.created_at else None,
        )


# ── Version ─────────────────────────────────────────────────────────


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
        return cls(
            id=ver.id,
            version_number=ver.version_number,
            lyrics=ver.lyrics,
            prompt=ver.prompt,
            bpm=ver.bpm,
            duration=ver.duration,
            key=ver.key,
            generation_params=ver.generation_params,
            created_at=ver.created_at.isoformat() if ver.created_at else None,
        )


# ── Song ────────────────────────────────────────────────────────────


class SongSummaryResponse(BaseModel):
    """Lightweight song for list endpoints — no generations."""

    id: str
    title: str
    album_id: str
    album_title: str = ""
    artist: str = ""
    track_number: int
    language: str = ""
    lyrics: str = ""
    prompt: str = ""
    bpm: int = 0
    duration: int = 180
    key: str = ""
    generation_params: dict | None = None
    version_count: int = 0
    generation_count: int = 0
    best_scores: dict | None = None
    best_rating: float | None = None
    created_at: str | None = None

    @classmethod
    def from_orm(cls, song: Song) -> SongSummaryResponse:
        ver = song.latest_version
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
            bpm=ver.bpm if ver else 0,
            duration=ver.duration if ver else 180,
            key=ver.key if ver else "",
            generation_params=ver.generation_params if ver else None,
            version_count=len(song.versions),
            generation_count=len(song.generations),
            created_at=song.created_at.isoformat() if song.created_at else None,
        )


class SongResponse(SongSummaryResponse):
    """Full song with generations — used by detail endpoints."""

    generations: list[GenerationResponse] = Field(default_factory=list)

    @classmethod
    def from_orm(cls, song: Song) -> SongResponse:
        best_gen = _best_generation(song.generations)

        best_scores: dict[str, object] | None = None
        if best_gen:
            best_scores = {}
            for s in best_gen.scores:
                if isinstance(s.value, dict):
                    best_scores.update(s.value)

        ver = song.latest_version
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
            bpm=ver.bpm if ver else 0,
            duration=ver.duration if ver else 180,
            key=ver.key if ver else "",
            generation_params=ver.generation_params if ver else None,
            version_count=len(song.versions),
            generation_count=len(song.generations),
            best_scores=best_scores if best_scores else None,
            best_rating=best_gen.rating.rating if best_gen and best_gen.rating else None,
            generations=[GenerationResponse.from_orm(g) for g in song.generations],
            created_at=song.created_at.isoformat() if song.created_at else None,
        )


def _best_generation(generations: list) -> object | None:
    rated = [g for g in generations if g.rating and not g.is_archived]
    if rated:
        return max(rated, key=lambda g: g.rating.rating)
    active = [g for g in generations if not g.is_archived]
    return active[0] if active else None


# ── Job ─────────────────────────────────────────────────────────────


class JobResponse(BaseModel):
    id: str
    type: str
    status: str
    progress: float = 0.0
    error: str | None = None
    error_type: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    @classmethod
    def from_orm(cls, job: Job) -> JobResponse:
        return cls(
            id=job.id,
            type=job.type,
            status=job.status,
            progress=job.progress,
            error=job.error,
            error_type=job.error_type,
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
        )


# ── Requests ────────────────────────────────────────────────────────


_GEN_PARAM_MAX_STRING_LENGTH = 2000

_VALID_INFER_METHODS = frozenset({"ode", "sde"})
_VALID_THINK_MODES = frozenset({"deep", "off", ""})


class GenerationParams(BaseModel):
    """Typed ACE-Step generation parameters — replaces untyped dict."""

    model_config = ConfigDict(extra="forbid")

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


class AlbumCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field("", max_length=200)


class SongCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    album_id: str = Field(max_length=64)
    lyrics: str = Field("", max_length=50_000)
    prompt: str = Field("", max_length=5_000)
    bpm: int = 0
    duration: int = Field(180, ge=1, le=600)
    key: str = Field("", max_length=10)
    language: str = Field("", max_length=10)
    generation_params: GenerationParams | None = None


class SongUpdateRequest(BaseModel):
    lyrics: str | None = Field(None, max_length=50_000)
    prompt: str | None = Field(None, max_length=5_000)
    bpm: int | None = None
    duration: int | None = Field(None, ge=1, le=600)
    key: str | None = Field(None, max_length=10)
    generation_params: GenerationParams | None = None


class GenerateRequest(BaseModel):
    count: int = Field(1, ge=1, le=10)


VALID_SCORER_NAMES = frozenset({
    "text_accuracy", "lyrical_coherence", "emotional_dynamics",
    "audiobox", "bpm_accuracy", "silence", "spectral_quality",
})


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


class GenerationDefaultsRequest(BaseModel):
    turbo: GenerationParams | None = None
    sft: GenerationParams | None = None


class ChatRequest(BaseModel):
    message: str = Field(max_length=10_000)
    context: str = Field("", max_length=20_000)


# ── Simple responses ────────────────────────────────────────────────


class StatusResponse(BaseModel):
    status: str = "ok"


class RateResponse(BaseModel):
    status: str = "ok"
    generation_id: str | None = None
    generation: str | None = None
    rating: float


class CleanupResponse(BaseModel):
    status: str = "ok"
    deleted: int


class CapabilitiesResponse(BaseModel):
    claude_api: bool
    claude_cli: bool
    generation: bool
    scoring: bool


class ChatResponse(BaseModel):
    response: str


# ── Auth ───────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)

    _check_strength = field_validator("password")(check_password_strength)


class ChangePasswordRequest(BaseModel):
    current: str = Field(min_length=1, max_length=128)
    new: str = Field(min_length=8, max_length=128, alias="new_password")

    _check_strength = field_validator("new")(check_password_strength)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["admin", "user"] = "user"

    _check_strength = field_validator("password")(check_password_strength)


class UpdateUserRequest(BaseModel):
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8, max_length=128)

    _check_strength = field_validator("password")(check_password_strength)


class UserResponse(BaseModel):
    id: str
    username: str
    role: str
    is_active: bool
    created_at: str | None = None

    @classmethod
    def from_orm(cls, user: User) -> UserResponse:
        return cls(
            id=user.id,
            username=user.username,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at.isoformat() if user.created_at else None,
        )


class AuthMeResponse(BaseModel):
    id: str
    username: str
    role: str


class SetupRequiredResponse(BaseModel):
    required: bool


class SessionResponse(BaseModel):
    id: str
    user_id: str
    username: str
    created_at: str | None = None
    expires_at: str | None = None
    ip_address: str = ""
    user_agent: str = ""

    @classmethod
    def from_orm(cls, sess: UserSession) -> SessionResponse:
        return cls(
            id=hashlib.sha256(sess.id.encode()).hexdigest(),
            user_id=sess.user_id,
            username=sess.user.username,
            created_at=sess.created_at.isoformat() if sess.created_at else None,
            expires_at=sess.expires_at.isoformat() if sess.expires_at else None,
            ip_address=sess.ip_address,
            user_agent=sess.user_agent,
        )


class LoginAttemptResponse(BaseModel):
    id: str
    ip_address: str
    username: str
    success: bool
    attempted_at: str | None = None

    @classmethod
    def from_orm(cls, attempt: LoginAttempt) -> LoginAttemptResponse:
        return cls(
            id=attempt.id,
            ip_address=attempt.ip_address,
            username=attempt.username,
            success=attempt.success,
            attempted_at=attempt.attempted_at.isoformat() if attempt.attempted_at else None,
        )


class AuditLogResponse(BaseModel):
    id: str
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str
    detail: str
    created_at: str | None = None

    @classmethod
    def from_orm(cls, entry: AuditLog) -> AuditLogResponse:
        return cls(
            id=entry.id,
            user_id=entry.user_id,
            action=entry.action,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            detail=entry.detail,
            created_at=entry.created_at.isoformat() if entry.created_at else None,
        )
