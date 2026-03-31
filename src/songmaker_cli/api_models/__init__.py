"""Pydantic models for API requests and responses.

Split by domain, re-exported here for backwards compatibility.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

from songmaker_cli.api_models.auth import (
    AuditLogResponse,
    AuthMeResponse,
    ChangePasswordRequest,
    CreateUserRequest,
    LoginAttemptResponse,
    LoginRequest,
    SessionResponse,
    SetupRequest,
    SetupRequiredResponse,
    UpdateUserRequest,
    UserResponse,
)
from songmaker_cli.api_models.settings import (
    AceStepStatusResponse,
    CapabilitiesResponse,
    ChatRequest,
    ChatResponse,
    DefaultConfigRequest,
    DefaultConfigResponse,
    GenerationDefaultsRequest,
    PresetCreateRequest,
    PresetResponse,
    PresetUpdateRequest,
    RateLimitItem,
    RateLimitsResponse,
    RateLimitUpdateRequest,
    UserRateLimitsResponse,
)
from songmaker_cli.api_models.songs import (
    VALID_SCORER_NAMES,
    AlbumCreateRequest,
    AlbumResponse,
    GenerateRequest,
    GenerationParams,
    GenerationResponse,
    RateRequest,
    ScoreRequest,
    SharedAlbumResponse,
    SharedGenerationResponse,
    SharedSongItem,
    SharedSongResponse,
    ShareResponse,
    SongCreateRequest,
    SongMoveRequest,
    SongResponse,
    SongSummaryResponse,
    SongUpdateRequest,
    StoredGenerationParams,
    VersionResponse,
)

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int


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
    def from_orm(cls, job) -> JobResponse:
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


__all__ = [
    "AceStepStatusResponse",
    "AlbumCreateRequest",
    "AlbumResponse",
    "AuditLogResponse",
    "AuthMeResponse",
    "CapabilitiesResponse",
    "ChangePasswordRequest",
    "ChatRequest",
    "ChatResponse",
    "CleanupResponse",
    "CreateUserRequest",
    "DefaultConfigRequest",
    "DefaultConfigResponse",
    "GenerateRequest",
    "GenerationDefaultsRequest",
    "GenerationParams",
    "GenerationResponse",
    "JobResponse",
    "LoginAttemptResponse",
    "LoginRequest",
    "PaginatedResponse",
    "PresetCreateRequest",
    "PresetResponse",
    "PresetUpdateRequest",
    "RateLimitItem",
    "RateLimitUpdateRequest",
    "RateLimitsResponse",
    "RateRequest",
    "RateResponse",
    "ScoreRequest",
    "SessionResponse",
    "SetupRequest",
    "SetupRequiredResponse",
    "ShareResponse",
    "SharedAlbumResponse",
    "SharedGenerationResponse",
    "SharedSongResponse",
    "SharedSongItem",
    "SongCreateRequest",
    "SongMoveRequest",
    "SongResponse",
    "SongSummaryResponse",
    "SongUpdateRequest",
    "StatusResponse",
    "StoredGenerationParams",
    "UpdateUserRequest",
    "UserRateLimitsResponse",
    "UserResponse",
    "VALID_SCORER_NAMES",
    "VersionResponse",
]
