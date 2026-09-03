from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from acestep_engine.models import AceStepConfig

TaskKind = Literal["generate", "download", "train_lora"]
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
    """Extra rejected: an unrecognized config field (a typo, a renamed
    ACE-Step param) must 422 here, not silently fall back to
    AceStepConfig's default for that field."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    config: AceStepConfig


class DownloadModelRequest(BaseModel):
    mode: str


class TaskCreatedResponse(BaseModel):
    task_id: str


class WorkerTaskEvent(BaseModel):
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)


class GenerationTaskResult(BaseModel):
    mode: str
    audio_path: str
    seed: int
    cot_caption: str = ""
    cot_lyrics: str = ""
    delivered_batch_size: int | None = None


class TrainLoraTaskResult(BaseModel):
    mode: str
    adapter_dir: str
    num_samples: int = 0
    final_loss: float | None = None


class DownloadTaskResult(BaseModel):
    mode: str
    size_bytes: int


TaskResult = GenerationTaskResult | TrainLoraTaskResult | DownloadTaskResult
"""What a finished task hands back — one model per ``TaskKind``."""


class TaskSnapshot(BaseModel):
    task_id: str
    kind: TaskKind
    state: TaskState
    progress: float = 0.0
    result: TaskResult | None = None
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
    vram_measured: bool
    available_modes: list[str]
    pinned: list[str] = []


class HealthResponse(BaseModel):
    status: Literal["ok"]


class TrainLoraRequest(BaseModel):
    mode: str
    dataset_dir: str
    output_dir: str
    lokr_linear_dim: int
    lokr_linear_alpha: int
    lokr_factor: int
    lokr_decompose_both: bool
    lokr_use_tucker: bool
    lokr_use_scalar: bool
    lokr_weight_decompose: bool
    learning_rate: float
    train_epochs: int
    train_batch_size: int
    gradient_accumulation: int
    save_every_n_epochs: int
    training_shift: float
    training_seed: int
    gradient_checkpointing: bool
    poll_interval_seconds: float


class TrainLoraResponse(BaseModel):
    task_id: str
