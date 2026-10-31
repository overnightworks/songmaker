"""Settings, presets, chat, and capabilities API models."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from agent_providers.errors import SafeRouteReason
from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator

from songmaker_cli.api_models.fields import ComputedTimestamp
from songmaker_cli.api_models.songs import _VALID_MODEL_MODES, GenerationParams
from songmaker_cli.constants import MEMORY_MAX_LENGTH
from songmaker_cli.db.models import ThemeChoice

if TYPE_CHECKING:
    from songmaker_cli.db.models import GenerationPreset


class GenerationDefaultsRequest(RootModel[dict[str, GenerationParams]]):

    @model_validator(mode="before")
    @classmethod
    def _validate_keys(cls, values: object) -> object:
        if isinstance(values, dict):
            invalid = set(values.keys()) - _VALID_MODEL_MODES
            if invalid:
                msg = f"Unknown model modes: {sorted(invalid)}. Valid: {sorted(_VALID_MODEL_MODES)}"
                raise ValueError(msg)
        return values


class PresetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    model_mode: str = Field(max_length=10)
    params: GenerationParams
    is_default: bool = False

    @field_validator("model_mode")
    @classmethod
    def _validate_model_mode(cls, v: str) -> str:
        if v not in _VALID_MODEL_MODES:
            msg = f"model_mode must be one of {sorted(_VALID_MODEL_MODES)}"
            raise ValueError(msg)
        return v


class PresetUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    params: GenerationParams | None = None
    is_default: bool | None = None


class PresetResponse(BaseModel):
    id: str
    name: str
    model_mode: str
    params: dict
    is_default: bool
    is_shared: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_orm(cls, preset: GenerationPreset) -> PresetResponse:
        return cls(
            id=preset.id,
            name=preset.name,
            model_mode=preset.model_mode,
            params=preset.params or {},
            is_default=preset.is_default,
            is_shared=preset.created_by is None,
            created_at=preset.created_at.isoformat(),
            updated_at=preset.updated_at.isoformat(),
        )


class DefaultConfigRequest(BaseModel):
    config: str | None = None


class DefaultConfigResponse(BaseModel):
    config: str | None = None


class ThemeSettings(BaseModel):
    theme: ThemeChoice


class ModelCapabilities(BaseModel):
    defaults: dict[str, object]
    max_inference_steps: int
    hidden_params: list[str]


class AvailableModelResponse(BaseModel):
    id: str
    is_active: bool
    capabilities: ModelCapabilities | None = None


class CowriterSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tail_token_budget: int


class ProviderRouteReadiness(BaseModel):
    state: Literal["ready", "not_configured", "disturbed", "unverified"]
    capability: Literal["tools_available", "text_only"]
    reason: SafeRouteReason | None = None
    probed_at: ComputedTimestamp = None
    setup_label: str


class ProviderRouteStatusResponse(BaseModel):
    models: list[str]
    catalogue_failure: SafeRouteReason | None = None
    catalog_source: str | None = None
    catalog_version: str | None = None
    readiness: ProviderRouteReadiness
    retained_model_id: str | None = None


class CowriterSettingsResponse(BaseModel):
    tail_token_budget: int


class CoverSettingsRequest(BaseModel):
    provider: str
    route: str
    model: str


class CoverSettingsResponse(BaseModel):
    provider: str
    route: Literal["cli", "api"]
    model: str
    allowed_providers: list[str]


class ProviderStatusResponse(BaseModel):
    provider: str
    cowriter_routes: dict[Literal["cli", "api"], ProviderRouteStatusResponse]
    cover_routes: dict[Literal["cli", "api"], ProviderRouteReadiness]


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: str

    @classmethod
    def from_orm(cls, msg) -> ChatMessageResponse:
        return cls(
            id=msg.id,
            role=msg.role,
            content=msg.content,
            created_at=msg.created_at.isoformat(),
        )


class ConversationResponse(BaseModel):
    id: str
    title: str | None
    created_at: str
    updated_at: str
    archived_at: str | None
    message_count: int
    last_message_at: str | None

    @classmethod
    def from_row(cls, row: dict) -> ConversationResponse:
        return cls(
            id=row["id"],
            title=row["title"],
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
            archived_at=(
                row["archived_at"].isoformat() if row["archived_at"] else None
            ),
            message_count=row["message_count"],
            last_message_at=(
                row["last_message_at"].isoformat()
                if row["last_message_at"] else None
            ),
        )

    @classmethod
    def from_orm(cls, conv, message_count: int = 0) -> ConversationResponse:
        return cls(
            id=conv.id,
            title=conv.title,
            created_at=conv.created_at.isoformat(),
            updated_at=conv.updated_at.isoformat(),
            archived_at=conv.archived_at.isoformat() if conv.archived_at else None,
            message_count=message_count,
            last_message_at=None,
        )


class ConversationListResponse(BaseModel):
    conversations: list[ConversationResponse]


class ConversationMessagesResponse(BaseModel):
    conversation_id: str
    title: str | None
    archived_at: str | None
    messages: list[ChatMessageResponse]
    turn_running: bool = Field(
        description=(
            "A co-writer turn in this conversation is still running on the server; "
            "its chat job decides, and a web-process restart ends a turn that process ran."
        ),
    )


class ChatTurnV2Request(BaseModel):
    message: str = Field(max_length=50_000)
    current_song_id: str | None = Field(default=None, max_length=36)
    mentioned_song_ids: list[str] = Field(default_factory=list, max_length=50)
    mentioned_version_ids: list[str] = Field(default_factory=list, max_length=50)
    mentioned_album_id: str | None = Field(default=None, max_length=36)
    current_generation_id: str | None = Field(default=None, max_length=36)


class AssistantTextEvent(BaseModel):
    type: Literal["assistant_text"] = "assistant_text"
    text: str


class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool_use_id: str
    name: str
    input: dict[str, object] = Field(default_factory=dict)


class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


class ChatTurnFinalFrame(BaseModel):
    """The frame a turn ends with when the assistant's answer is stored."""

    type: Literal["final"] = "final"
    conversation_id: str
    user_message: ChatMessageResponse
    assistant_message: ChatMessageResponse


class ChatTurnProblem(StrEnum):
    """Why a co-writer turn could not run; the panel words each one."""

    UNAVAILABLE = "unavailable"
    BUSY = "busy"
    NOT_ENABLED = "not_enabled"
    SIGN_IN_AGAIN = "sign_in_again"


class ChatTurnProblemFrame(BaseModel):
    """The frame a turn ends with when the agent service did not run it.

    ``retry_after_seconds`` is set only for ``busy``: the wait the service named.
    """

    type: Literal["error"] = "error"
    status: int
    problem: ChatTurnProblem
    retry_after_seconds: int | None = None


class ChatTurnFailureFrame(BaseModel):
    """The frame a turn ends with when the endpoint itself could not finish."""

    type: Literal["error"] = "error"
    status: int
    message: str


class MemoryScopeResponse(BaseModel):
    scope: Literal["user", "song", "album"]
    target_id: str
    body: str
    updated_at: ComputedTimestamp = None

    @classmethod
    def from_orm(cls, scope: str, target_id: str, row) -> MemoryScopeResponse:
        if row is None:
            return cls(scope=scope, target_id=target_id, body="", updated_at=None)
        return cls(
            scope=scope,
            target_id=target_id,
            body=row.body,
            updated_at=row.updated_at.isoformat() if row.updated_at else None,
        )


class MemoryBundleResponse(BaseModel):
    user: MemoryScopeResponse
    song: MemoryScopeResponse | None = None
    album: MemoryScopeResponse | None = None


class MemoryUpdateRequest(BaseModel):
    body: str = Field(max_length=MEMORY_MAX_LENGTH)


class CapabilitiesResponse(BaseModel):
    claude_api: bool
    claude_cli: bool
    generation: bool
    scoring: bool
    chat_model: str


class RateLimitItem(BaseModel):
    setting_key: str
    value: int
    is_override: bool = False

    @classmethod
    def from_orm(cls, obj, is_override: bool = False) -> RateLimitItem:
        return cls(
            setting_key=obj.setting_key,
            value=obj.value,
            is_override=is_override,
        )


class RateLimitsResponse(BaseModel):
    settings: list[RateLimitItem]


class RateLimitUpdateRequest(BaseModel):
    settings: dict[str, int]
