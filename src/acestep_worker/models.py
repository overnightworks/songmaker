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
    loaded: list[str]
    target_loading: str | None
    queue_depth: int
    vram_used_gb: float
    vram_total_gb: float
    available_modes: list[str]


class HealthResponse(BaseModel):
    status: Literal["ok"]
