"""Domain models for the ACE-Step music engine."""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class AceStepConfig:
    """Configuration for an ACE-Step music generation request."""

    prompt: str
    lyrics: str
    bpm: int | None = 120
    duration: int = 60
    key: str = ""
    time_signature: str = ""
    vocal_language: str = "en"
    instrumental: bool = False
    seed: int = -1
    inference_steps: int = 8
    guidance_scale: float = 0.0
    shift: float = 3.0
    think_mode: str = "deep"
    lm_temperature: float = 0.85
    lm_top_k: int = 0
    lm_top_p: float = 0.9
    lm_cfg_scale: float = 2.0
    lm_negative_prompt: str = ""
    infer_method: str = "ode"
    batch_size: int = 1


@dataclass(frozen=True)
class AceStepResult:
    """Result from an ACE-Step generation.

    Contains raw WAV bytes from the server. The caller is responsible
    for decoding to numpy arrays via audio_engine.read_wav_bytes().
    """

    wav_bytes: bytes
    seed: int


@dataclass(frozen=True)
class ServerInfo:
    """ACE-Step server identity returned by /health."""

    model: str
    lm_model: str
    version: str


class TaskSubmitData(BaseModel):
    """Inner data from a /release_task response."""

    task_id: str = ""
    status: str = ""


class TaskSubmitResponse(BaseModel):
    """Top-level /release_task response envelope."""

    data: TaskSubmitData = Field(default_factory=TaskSubmitData)
    code: int = 200


class ResultItem(BaseModel):
    """A single generation result entry from the server."""

    file: str = ""
    seed_value: str = ""

    @property
    def seed(self) -> int:
        """Parse seed from server's seed_value string (e.g. '12345' or '')."""
        try:
            return int(self.seed_value)
        except (ValueError, TypeError):
            return -1


class TaskQueryEntry(BaseModel):
    """One entry in the /query_result data list."""

    task_id: str = ""
    status: int = 0
    result: str | list = "[]"
    progress_text: str = ""

    def parse_result_items(self) -> list[ResultItem]:
        raw = self.result
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return []
        if isinstance(raw, list):
            return [ResultItem.model_validate(item) for item in raw if isinstance(item, dict)]
        return []


class TaskQueryResponse(BaseModel):
    """Top-level /query_result response envelope."""

    data: list[TaskQueryEntry] = Field(default_factory=list)
