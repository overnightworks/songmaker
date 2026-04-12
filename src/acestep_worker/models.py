from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TaskKind = Literal["generate", "download"]
TaskState = Literal["pending", "running", "done", "error"]
EventType = Literal["progress", "done", "error"]


class LoadModelRequest(BaseModel):
    mode: str


class EvictModelRequest(BaseModel):
    mode: str


class PinModelRequest(BaseModel):
    mode: str


class UnpinModelRequest(BaseModel):
    mode: str


class PinModelResponse(BaseModel):
    mode: str
    pinned: list[str]


class RestartResponse(BaseModel):
    status: Literal["restarting"]
    pid: int


class LoadedModelDetailItem(BaseModel):
    mode: str
    size_gb: float


class LoadModelResponse(BaseModel):
    loaded: list[str]
    evicted: list[str]
    target_loading: str | None = None


class EvictModelResponse(BaseModel):
    loaded: list[str]
    evicted: list[str]


class GenerateRequest(BaseModel):
    mode: str
    config: dict[str, Any]


class DownloadModelRequest(BaseModel):
    mode: str


class TaskCreatedResponse(BaseModel):
    task_id: str


class WorkerTaskEvent(BaseModel):
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)


class TaskSnapshot(BaseModel):
    task_id: str
    kind: TaskKind
    state: TaskState
    progress: float = 0.0
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class LoadedModelsResponse(BaseModel):
    loaded: list[LoadedModelDetailItem]
    target_loading: str | None
    loading_started_at: str | None = None
    loading_last_log_line: str | None = None
    queue_depth: int
    vram_used_gb: float
    vram_total_gb: float
    available_modes: list[str]
    pinned: list[str] = []


class HealthResponse(BaseModel):
    status: Literal["ok"]


class GenerationTaskResult(BaseModel):
    mode: str
    audio_path: str
    seed: int
    cot_caption: str = ""
    cot_lyrics: str = ""
