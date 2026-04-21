from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

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


class TrainLoraRequest(BaseModel):
    mode: str
    dataset_dir: str
    output_dir: str
    lokr_linear_dim: int = 64
    lokr_linear_alpha: int = 128
    lokr_factor: int = -1
    lokr_decompose_both: bool = False
    lokr_use_tucker: bool = False
    lokr_use_scalar: bool = False
    lokr_weight_decompose: bool = True
    learning_rate: float = 0.03
    train_epochs: int = 500
    train_batch_size: int = 1
    gradient_accumulation: int = 4
    save_every_n_epochs: int = 5
    training_shift: float = 3.0
    training_seed: int = 42
    gradient_checkpointing: bool = False
    poll_interval_seconds: float = 5.0


class TrainLoraTaskResult(BaseModel):
    mode: str
    adapter_dir: str
    num_samples: int = 0
    final_loss: float | None = None


class TrainLoraResponse(BaseModel):
    task_id: str
