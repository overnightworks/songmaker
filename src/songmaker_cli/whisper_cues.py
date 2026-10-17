"""Typed Whisper time marks stored on a generation."""

from __future__ import annotations

import math
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


class TimedTranscriptSpan(BaseModel):
    """A piece of transcribed text with the playback span it was sung in."""

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
    def _end_not_before_start(self) -> Self:
        if self.end < self.start:
            raise ValueError("end must not be before start")
        return self


class WhisperWordCue(TimedTranscriptSpan):
    """A single transcribed word — the finest time mark Whisper produces."""


class WhisperCue(TimedTranscriptSpan):
    """A transcribed segment. Carries its words when the take was scored with
    word timestamps; takes scored before that carry none.
    """

    words: list[WhisperWordCue] | None = Field(default=None, min_length=1)

    @classmethod
    def from_orm(cls, raw: object) -> WhisperCue:
        return cls.model_validate(raw)


def stored_whisper_cues(value: object) -> list[dict] | None:
    """Normalize cues for the JSON column.

    Dumped without its null fields so a cue stores only the time marks it
    actually has, and a wordless cue keeps the shape it had before word
    timestamps existed.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        msg = f"whisper_cues must be a list or None, got {type(value).__name__}"
        raise TypeError(msg)
    return [
        WhisperCue.model_validate(item).model_dump(exclude_none=True) for item in value
    ]


def generation_whisper_cues(value: object) -> list[WhisperCue] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        msg = f"whisper_cues must be a list or None, got {type(value).__name__}"
        raise TypeError(msg)
    return [WhisperCue.from_orm(item) for item in value]
