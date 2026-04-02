"""Settings, presets, chat, and capabilities API models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, RootModel, field_validator, model_validator

from songmaker_cli.api_models.songs import _VALID_MODEL_MODES, GenerationParams

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
            created_at=preset.created_at.isoformat() if preset.created_at else "",
            updated_at=preset.updated_at.isoformat() if preset.updated_at else "",
        )


class DefaultConfigRequest(BaseModel):
    config: str | None = None


class DefaultConfigResponse(BaseModel):
    config: str | None = None


class AvailableModelResponse(BaseModel):
    id: str
    is_active: bool


class ClaudeModelsRequest(BaseModel):
    chat_model: str
    scoring_model: str


class ClaudeModelsResponse(BaseModel):
    chat_model: str
    scoring_model: str
    allowed_models: list[str]


class ChatRequest(BaseModel):
    message: str = Field(max_length=50_000)
    context: str = Field("", max_length=10_000)


class ChatResponse(BaseModel):
    response: str


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


class AceStepStatusResponse(BaseModel):
    online: bool
    model: str | None
    lm_model: str | None
    jobs: dict


class ReinitializeRequest(BaseModel):
    target_model: str | None = None
