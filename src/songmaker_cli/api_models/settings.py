"""Settings, presets, chat, and capabilities API models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, RootModel, field_validator, model_validator

from songmaker_cli.api_models.fields import ComputedTimestamp
from songmaker_cli.api_models.songs import _VALID_MODEL_MODES, GenerationParams
from songmaker_cli.constants import MEMORY_MAX_LENGTH

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


class ModelCapabilities(BaseModel):
    defaults: dict[str, object]
    max_inference_steps: int
    hidden_params: list[str]


class AvailableModelResponse(BaseModel):
    id: str
    is_active: bool
    capabilities: ModelCapabilities | None = None


class ClaudeModelsRequest(BaseModel):
    chat_model: str
    scoring_model: str


class ClaudeModelsResponse(BaseModel):
    chat_model: str
    scoring_model: str
    allowed_models: list[str]


class CowriterSettingsRequest(BaseModel):
    provider: str
    model: str
    tail_token_budget: int | None = None


class CowriterSettingsResponse(BaseModel):
    provider: str
    model: str
    allowed_providers: list[str]
    allowed_models: list[str]
    models_by_provider: dict[str, list[str]]
    models_errors: dict[str, str] = Field(default_factory=dict)
    tail_token_budget: int


class JudgeSettingsRequest(BaseModel):
    provider: str
    model: str


class JudgeSettingsResponse(BaseModel):
    provider: str
    model: str
    allowed_providers: list[str]
    allowed_models: list[str]
    models_by_provider: dict[str, list[str]]
    models_errors: dict[str, str] = Field(default_factory=dict)


class ProviderStatusResponse(BaseModel):
    provider: str
    configured: bool
    setup_method: Literal["api_key", "claude_cli"] | None = None
    environment_key: str | None = None
    missing_dependency: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(max_length=50_000)
    context: str = Field("", max_length=10_000)


class ChatResponse(BaseModel):
    response: str


class SendChatRequest(BaseModel):
    message: str = Field(max_length=50_000)
    mentioned_song_ids: list[str] = Field(default_factory=list)
    mentioned_version_ids: list[str] = Field(default_factory=list)


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


class ChatTurnResponse(BaseModel):
    user_message: ChatMessageResponse
    assistant_message: ChatMessageResponse


class ChatHistoryResponse(BaseModel):
    messages: list[ChatMessageResponse]


class RecentChatItem(BaseModel):
    song_id: str
    title: str
    message_count: int
    last_message_at: str | None


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


class ChatTurnV2Request(BaseModel):
    message: str = Field(max_length=50_000)
    current_song_id: str | None = Field(default=None, max_length=36)
    mentioned_song_ids: list[str] = Field(default_factory=list, max_length=50)
    mentioned_version_ids: list[str] = Field(default_factory=list, max_length=50)
    mentioned_album_id: str | None = Field(default=None, max_length=36)
    current_generation_id: str | None = Field(default=None, max_length=36)


class ChatTurnV2Response(BaseModel):
    conversation_id: str
    user_message: ChatMessageResponse
    assistant_message: ChatMessageResponse


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
    scoring_model: str


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


class UserRateLimitsResponse(BaseModel):
    user_id: str
    overrides: list[RateLimitItem]
    effective: list[RateLimitItem]

