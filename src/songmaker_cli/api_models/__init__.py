"""Pydantic models for API requests and responses.

Split by domain, re-exported here for backwards compatibility.

The value objects shared with persistence (generation params, Whisper cues)
live beneath both layers and are re-exported here because
``scripts/generate_types.py`` reads this module's ``__all__`` to find the
models that reach ``types.ts``.
"""

from __future__ import annotations

from agent_providers.events import AssistantTextEvent, ToolCallEvent, ToolResultEvent
from pydantic import BaseModel

from songmaker_cli.api_models.auth import AuthMeResponse, LogoutResponse
from songmaker_cli.api_models.cover_suggestions import (
    CoverSuggestionResponse,
    CoverSuggestionSelectionRequest,
    CoverSuggestionsResponse,
)
from songmaker_cli.api_models.health import HealthResponse
from songmaker_cli.api_models.jobs import GenerationUnavailableResponse, JobResponse
from songmaker_cli.api_models.library import (
    LIBRARY_SORT_VALUES,
    LibraryAlbumHit,
    LibraryListenItem,
    LibraryListenResponse,
    LibrarySearchHit,
    LibrarySearchResponse,
    LibrarySongHit,
    LibrarySort,
    LibraryWriteItem,
    LibraryWriteResponse,
)
from songmaker_cli.api_models.loras import (
    AdminUserLoraResponse,
    LoraCapacityErrorResponse,
    LoraCapacityReason,
    OwnPlayableTakeListResponse,
    OwnPlayableTakeResponse,
    UserLoraCreateRequest,
    UserLoraListResponse,
    UserLoraResponse,
    UserLoraSampleFromGenerationRequest,
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
    ChatMessageResponse,
    ChatTurnFailureFrame,
    ChatTurnFinalFrame,
    ChatTurnRouteErrorFrame,
    ChatTurnV2Request,
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationResponse,
    CoverSettingsRequest,
    CoverSettingsResponse,
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
    ProviderStatusResponse,
    RateLimitItem,
    RateLimitsResponse,
    RateLimitUpdateRequest,
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
from songmaker_cli.generation_params import (
    BaseGenerationParams,
    CoverTaskParams,
    RepaintTaskParams,
    StoredGenerationParams,
)
from songmaker_cli.whisper_cues import (
    WhisperCue,
    WhisperWordCue,
)


class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int
    offset: int
    limit: int
    has_more: bool


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
    scheduled_hour_utc: int
    dry_run: bool


__all__ = [
    "AddAlbumToPlaylistRequest",
    "AddAlbumToPlaylistResponse",
    "AddGenerationToPlaylistRequest",
    "AddSongToPlaylistRequest",
    "AdminUserLoraResponse",
    "AlbumCoverUrls",
    "AlbumCreateRequest",
    "AlbumResponse",
    "AlbumUpdateRequest",
    "BaseGenerationParams",
    "BulkDeleteRequest",
    "BulkDeleteResponse",
    "AuthMeResponse",
    "CapabilitiesResponse",
    "ChatMessageResponse",
    "ChatTurnV2Request",
    "ChatTurnFailureFrame",
    "ChatTurnFinalFrame",
    "ChatTurnRouteErrorFrame",
    "AssistantTextEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "CleanupResponse",
    "MemoryBundleResponse",
    "MemoryScopeResponse",
    "MemoryUpdateRequest",
    "ConversationListResponse",
    "CowriterSettingsRequest",
    "CowriterSettingsResponse",
    "ConversationMessagesResponse",
    "ConversationResponse",
    "CoverSettingsRequest",
    "CoverSettingsResponse",
    "CoverRequest",
    "CoverSuggestionResponse",
    "CoverSuggestionSelectionRequest",
    "CoverSuggestionsResponse",
    "CoverTaskParams",
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
    "HealthResponse",
    "JobResponse",
    "JudgeSettingsRequest",
    "JudgeSettingsResponse",
    "LogoutResponse",
    "LoraCapacityErrorResponse",
    "GenerationUnavailableResponse",
    "LoraCapacityReason",
    "LIBRARY_SORT_VALUES",
    "LastFailedGenerationResponse",
    "LibraryAlbumHit",
    "LibraryListenItem",
    "LibraryListenResponse",
    "LibrarySearchHit",
    "LibrarySearchResponse",
    "LibrarySongHit",
    "LibrarySort",
    "LibraryWriteItem",
    "LibraryWriteResponse",
    "LibraryPoolQueueResponse",
    "LibraryPoolTakeResponse",
    "LibraryTakePool",
    "LoadedModelDetail",
    "LoadModelOnWorkerRequest",
    "ModelAvailability",
    "OwnPlayableTakeListResponse",
    "OwnPlayableTakeResponse",
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
    "ProviderStatusResponse",
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
    "ResourceHelloEvent",
    "ResourceResyncEvent",
    "ScorerSchemaItem",
    "ScoreRequest",
    "ScoringSchemaResponse",
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
    "UserLoraCreateRequest",
    "UserLoraListResponse",
    "UserLoraResponse",
    "UserLoraSampleFromGenerationRequest",
    "UserLoraSamplePatchRequest",
    "UserLoraSampleResponse",
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
]
