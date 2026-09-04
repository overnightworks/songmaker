"""ACE-Step worker pool API models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from songmaker_cli.db.models import AceStepWorker


class WorkerRegisterRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=50)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    gpu_id: int | None = None
    vram_total_gb: float | None = None


class WorkerRegisterResponse(BaseModel):
    worker_id: str
    registered_at: str


class WorkerIdentity(BaseModel):
    id: str
    host: str
    port: int
    gpu_id: int | None
    vram_total_gb: float | None
    registered_at: str
    last_register_at: str

    @classmethod
    def from_orm(cls, worker: AceStepWorker) -> WorkerIdentity:
        return cls(
            id=worker.id,
            host=worker.host,
            port=worker.port,
            gpu_id=worker.gpu_id,
            vram_total_gb=worker.vram_total_gb,
            registered_at=worker.registered_at.isoformat(),
            last_register_at=worker.last_register_at.isoformat(),
        )


class LoadedModelDetail(BaseModel):
    mode: str
    size_gb: float


class WorkerEphemeralState(BaseModel):
    loaded: list[LoadedModelDetail]
    target_loading: str | None = None
    loading_started_at: str | None = None
    loading_last_log_line: str | None = None
    queue_depth: int = 0
    training_hold_seconds: int | None = None
    vram_used_gb: float | None = None
    vram_total_gb: float | None = None
    vram_measured: bool | None = None
    available_modes: list[str] = []
    pinned: list[str] = []
    last_heartbeat_at: str | None = None
    # None means the heartbeat predates this field (an old worker build) —
    # distinct from False (NVML present but the GPU didn't answer). The
    # admin worker pool (issue #367) shows a different sentence for each;
    # neither is an operable "Idle" worker.
    gpu_healthy: bool | None = None
    gpu_health_detail: str | None = None

    @field_validator("loaded", mode="before")
    @classmethod
    def normalize_legacy_loaded_models(cls, loaded: object) -> object:
        """Keep accepting the string form emitted by older worker builds."""
        if not isinstance(loaded, list):
            return loaded
        return [
            {"mode": model, "size_gb": 0.0} if isinstance(model, str) else model
            for model in loaded
        ]


WorkerStatus = Literal["online", "loading", "offline"]

# No worker online means unknown, not "not downloaded" — a third outcome.
ModelAvailability = Literal["downloaded", "not_downloaded", "unknown_no_worker"]


class WorkerInfo(BaseModel):
    identity: WorkerIdentity
    state: WorkerEphemeralState | None
    status: WorkerStatus


class WorkerPoolResponse(BaseModel):
    workers: list[WorkerInfo]


class RegistryModelResponse(BaseModel):
    mode: str
    availability: ModelAvailability
    loaded_on: list[str]
    loading_on: list[str]


class RegistryResponse(BaseModel):
    models: list[RegistryModelResponse]


class LoadModelOnWorkerRequest(BaseModel):
    mode: str = Field(min_length=1, max_length=20)


class EvictModelOnWorkerRequest(BaseModel):
    mode: str = Field(min_length=1, max_length=20)


class PinModelOnWorkerRequest(BaseModel):
    mode: str = Field(min_length=1, max_length=20)


class UnpinModelOnWorkerRequest(BaseModel):
    mode: str = Field(min_length=1, max_length=20)
