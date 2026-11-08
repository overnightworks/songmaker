"""The job statuses, types and phases, shared by every layer that reads or writes a job."""

from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


JOB_ACTIVE_STATUSES = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})
JOB_TERMINAL_STATUSES = frozenset({
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.PARTIAL,
    JobStatus.CANCELLED,
})


class JobType(StrEnum):
    COVER = "cover"
    GENERATE = "generate"
    SCORE = "score"
    CHAT = "chat"
    LORA_TRAINING = "lora_training"
    LOAD_MODEL_ON_WORKER = "load_model_on_worker"
    DOWNLOAD_MODEL_ON_WORKER = "download_model_on_worker"


class GenerationPhase(StrEnum):
    """The stretch of one take a generate job is in."""

    LOADING_MODEL = "loading_model"
    WRITING = "writing"
    RENDERING = "rendering"
    SAVING_TAKE = "saving_take"


class WorkerLivenessSignal(StrEnum):
    MUSIC = "music"
    SCORING = "scoring"
    MODEL_EXECUTION = "music_and_acestep"


class JobFunction(StrEnum):
    GENERATE = "generate"
    SCORE = "score"
    LOAD_MODEL_ON_WORKER = "load_model_on_worker"
    DOWNLOAD_MODEL_ON_WORKER = "download_model_on_worker"
    LORA_TRAINING = "lora_training"
