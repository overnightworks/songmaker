"""Typed Whisper time marks stored on a generation."""

from __future__ import annotations

import math

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


class WhisperCue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: float = Field(description="Start time in seconds")
    end: float = Field(description="End time in seconds")
    text: str = Field(min_length=1)

    @field_validator("start", "end")
    @classmethod
    def _finite_non_negative_seconds(cls, value: float, info: ValidationInfo) -> float:
        if not math.isfinite(value):
            raise ValueError(f"{info.field_name} must be a finite number of seconds")
        if value < 0:
            raise ValueError(f"{info.field_name} must not be negative")
        return value

    @field_validator("text")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text must not be empty")
        return stripped

    @model_validator(mode="after")
    def _end_not_before_start(self) -> WhisperCue:
        if self.end < self.start:
            raise ValueError("end must not be before start")
        return self

    @classmethod
    def from_orm(cls, raw: object) -> WhisperCue:
        return cls.model_validate(raw)


def stored_whisper_cues(value: object) -> list[dict] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        msg = f"whisper_cues must be a list or None, got {type(value).__name__}"
        raise TypeError(msg)
    return [WhisperCue.model_validate(item).model_dump() for item in value]


def generation_whisper_cues(value: object) -> list[WhisperCue] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        msg = f"whisper_cues must be a list or None, got {type(value).__name__}"
        raise TypeError(msg)
    return [WhisperCue.from_orm(item) for item in value]
