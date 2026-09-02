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
from songmaker_cli.api_models.generation_params import (
    BaseGenerationParams,
    CoverTaskParams,
    RepaintTaskParams,
    StoredGenerationParams,
)
from songmaker_cli.api_models.library import (
    LIBRARY_SORT_VALUES,
    LibraryAlbumHit,
    LibrarySearchHit,
    LibrarySearchResponse,
    LibrarySongHit,
    LibrarySort,
    ShareInventoryItem,
    ShareInventoryType,
)
from songmaker_cli.api_models.loras import (
    UserLoraCreateRequest,
    UserLoraListResponse,
    UserLoraResponse,
    UserLoraSampleCreateRequest,
    UserLoraSamplePatchRequest,
    UserLoraSampleResponse,
)
from songmaker_cli.api_models.playlists import (
    AddAlbumToPlaylistRequest,
    AddAlbumToPlaylistResponse,
    AddGenerationToPlaylistRequest,
    AddSongToPlaylistRequest,
    PlaylistAlbumSkipResponse,
    PlaylistCreateRequest,
    PlaylistDetailResponse,
    PlaylistEntryResponse,
    PlaylistResponse,
    PlaylistUpdateRequest,
    ReorderPlaylistEntryRequest,
    SharedPlaylistEntryResponse,
    SharedPlaylistResponse,
)
from songmaker_cli.api_models.queue_streams import (
    DEFAULT_LIBRARY_TAKE_POOL,
    LibraryPoolQueueResponse,
    LibraryPoolTakeResponse,
    LibraryTakePool,
    QueueStreamLibraryRequest,
    QueueStreamManifestResponse,
    QueueStreamPinResponse,
    QueueStreamSkipResponse,
    QueueStreamSnapshotRequest,
    QueueStreamTrackRequest,
    QueueStreamTrackResponse,
)
from songmaker_cli.api_models.resource_events import (
    GenerationCreatedResourceEvent,
    ResourceHelloEvent,
    ResourceResyncEvent,
)
from songmaker_cli.api_models.settings import (
    CapabilitiesResponse,
    ChatHistoryResponse,
    ChatMessageResponse,
    ChatRequest,
    ChatResponse,
    ChatTurnResponse,
    ChatTurnV2Request,
    ChatTurnV2Response,
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationResponse,
    CowriterSettingsRequest,
    CowriterSettingsResponse,
    DefaultConfigRequest,
    DefaultConfigResponse,
    GenerationDefaultsRequest,
    JudgeSettingsRequest,
    JudgeSettingsResponse,
    MemoryBundleResponse,
    MemoryScopeResponse,
    MemoryUpdateRequest,
    PresetCreateRequest,
    PresetResponse,
    PresetUpdateRequest,
    ProviderNotConfiguredDetail,
    ProviderStatusResponse,
    ProviderSurfaceState,
    ProviderSurfaceStatus,
    RateLimitItem,
    RateLimitsResponse,
    RateLimitUpdateRequest,
    RecentChatItem,
    SendChatRequest,
    UserRateLimitsResponse,
)
from songmaker_cli.api_models.songs import (
    VALID_SCORER_NAMES,
    AlbumCoverUrls,
    AlbumCreateRequest,
    AlbumResponse,
    AlbumUpdateRequest,
    BulkDeleteRequest,
    BulkDeleteResponse,
    CoverRequest,
    GenerateRequest,
    GenerationParams,
    GenerationResponse,
    RateRequest,
    RepaintRequest,
    ScoreRequest,
    ScorerSchemaItem,
    ScoringSchemaResponse,
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
    TitleUpdateRequest,
    VersionResponse,
)
from songmaker_cli.api_models.whisper import (
    WhisperCue,
    WhisperWordCue,
    stored_whisper_cues,
)
from songmaker_cli.api_models.workers import (
    EvictModelOnWorkerRequest,
    LoadedModelDetail,
    LoadModelOnWorkerRequest,
    ModelAvailability,
    PinModelOnWorkerRequest,
    RegistryModelResponse,
    RegistryResponse,
    UnpinModelOnWorkerRequest,
    WorkerEphemeralState,
    WorkerIdentity,
    WorkerInfo,
    WorkerPoolResponse,
    WorkerRegisterRequest,
    WorkerRegisterResponse,
)

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int
    has_more: bool


class JobResponse(BaseModel):
    id: str
    type: str
    status: str
    progress: float = 0.0
    error: str | None = None
    error_type: str | None = None
    queue_position: int | None = None
    started_at: str | None = None
    completed_at: str | None = None

    @classmethod
    def from_orm(cls, job, queue_position: int | None = None) -> JobResponse:
        return cls(
            id=job.id,
            type=job.type,
            status=job.status,
            progress=job.progress,
            error=job.error,
            error_type=job.error_type,
            queue_position=queue_position,
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
        )


class LastFailedGenerationResponse(BaseModel):
    """A song's last failed generate/repaint/cover job, if it is still the
    last word on the song's takes (see api_last_failed_generation)."""

    job: JobResponse | None = None


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


class GenerationRetentionReportResponse(BaseModel):
    archived_ids: list[str]
    deleted_ids: list[str]
    archived_count: int
    deleted_count: int
    retention_days: int
    hard_delete_days: int
    dry_run: bool


__all__ = [
    "AddAlbumToPlaylistRequest",
    "AddAlbumToPlaylistResponse",
    "AddGenerationToPlaylistRequest",
    "AddSongToPlaylistRequest",
    "AlbumCoverUrls",
    "AlbumCreateRequest",
    "AlbumResponse",
    "AlbumUpdateRequest",
    "AuditLogResponse",
    "BaseGenerationParams",
    "BulkDeleteRequest",
    "BulkDeleteResponse",
    "AuthMeResponse",
    "CapabilitiesResponse",
    "ChangePasswordRequest",
    "ChatHistoryResponse",
    "ChatMessageResponse",
    "ChatRequest",
    "ChatResponse",
    "ChatTurnResponse",
    "ChatTurnV2Request",
    "ChatTurnV2Response",
    "CleanupResponse",
    "MemoryBundleResponse",
    "MemoryScopeResponse",
    "MemoryUpdateRequest",
    "ConversationListResponse",
    "CowriterSettingsRequest",
    "CowriterSettingsResponse",
    "ConversationMessagesResponse",
    "ConversationResponse",
    "CoverRequest",
    "CoverTaskParams",
    "CreateUserRequest",
    "DEFAULT_LIBRARY_TAKE_POOL",
    "DefaultConfigRequest",
    "DefaultConfigResponse",
    "EvictModelOnWorkerRequest",
    "GenerateRequest",
    "GenerationCreatedResourceEvent",
    "GenerationDefaultsRequest",
    "GenerationParams",
    "GenerationResponse",
    "GenerationRetentionReportResponse",
    "JobResponse",
    "JudgeSettingsRequest",
    "JudgeSettingsResponse",
    "LIBRARY_SORT_VALUES",
    "LastFailedGenerationResponse",
    "LibraryAlbumHit",
    "LibrarySearchHit",
    "LibrarySearchResponse",
    "LibrarySongHit",
    "LibrarySort",
    "LibraryPoolQueueResponse",
    "LibraryPoolTakeResponse",
    "LibraryTakePool",
    "LoadedModelDetail",
    "LoadModelOnWorkerRequest",
    "LoginAttemptResponse",
    "LoginRequest",
    "ModelAvailability",
    "PaginatedResponse",
    "PinModelOnWorkerRequest",
    "PlaylistAlbumSkipResponse",
    "PlaylistCreateRequest",
    "PlaylistDetailResponse",
    "PlaylistEntryResponse",
    "PlaylistResponse",
    "PlaylistUpdateRequest",
    "PresetCreateRequest",
    "PresetResponse",
    "PresetUpdateRequest",
    "ProviderNotConfiguredDetail",
    "ProviderStatusResponse",
    "ProviderSurfaceState",
    "ProviderSurfaceStatus",
    "QueueStreamLibraryRequest",
    "QueueStreamManifestResponse",
    "QueueStreamPinResponse",
    "QueueStreamSnapshotRequest",
    "QueueStreamSkipResponse",
    "QueueStreamTrackRequest",
    "QueueStreamTrackResponse",
    "RateLimitItem",
    "RateLimitUpdateRequest",
    "RateLimitsResponse",
    "RateRequest",
    "RegistryModelResponse",
    "RegistryResponse",
    "RepaintRequest",
    "RepaintTaskParams",
    "ReorderPlaylistEntryRequest",
    "RateResponse",
    "RecentChatItem",
    "ResourceHelloEvent",
    "ResourceResyncEvent",
    "ScorerSchemaItem",
    "ScoreRequest",
    "ScoringSchemaResponse",
    "SendChatRequest",
    "SessionResponse",
    "SetupRequest",
    "SetupRequiredResponse",
    "ShareInventoryItem",
    "ShareInventoryType",
    "ShareResponse",
    "SharedPlaylistEntryResponse",
    "SharedPlaylistResponse",
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
    "TitleUpdateRequest",
    "UnpinModelOnWorkerRequest",
    "UpdateUserRequest",
    "UserLoraCreateRequest",
    "UserLoraListResponse",
    "UserLoraResponse",
    "UserLoraSampleCreateRequest",
    "UserLoraSamplePatchRequest",
    "UserLoraSampleResponse",
    "UserRateLimitsResponse",
    "UserResponse",
    "VALID_SCORER_NAMES",
    "VersionResponse",
    "WorkerEphemeralState",
    "WorkerIdentity",
    "WorkerInfo",
    "WorkerPoolResponse",
    "WhisperCue",
    "WhisperWordCue",
    "WorkerRegisterRequest",
    "WorkerRegisterResponse",
    "stored_whisper_cues",
]
