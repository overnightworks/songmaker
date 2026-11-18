"""The arguments of a queued job: one record per job type, stored on the job's row.

A job type that runs from the arguments of its own row (cover, chat) has no record.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from songmaker_cli.generation_params import CoverTaskParams, RepaintTaskParams
from songmaker_cli.job_types import JobType


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GeneratePayload(_Payload):
    """A generate job; a repaint or a cover of a take carries its task."""

    job_type: Literal[JobType.GENERATE] = JobType.GENERATE
    song_id: str
    version_id: str
    count: int
    user_id: str
    seed: int | None
    target_model: str
    task_params: RepaintTaskParams | CoverTaskParams | None


class ScorePayload(_Payload):
    job_type: Literal[JobType.SCORE] = JobType.SCORE
    gen_id: str
    scorers: list[str] | None = None


class LoraTrainingPayload(_Payload):
    job_type: Literal[JobType.LORA_TRAINING] = JobType.LORA_TRAINING
    lora_id: str
    user_id: str
    target_mode: str


class LoadModelPayload(_Payload):
    job_type: Literal[JobType.LOAD_MODEL_ON_WORKER] = JobType.LOAD_MODEL_ON_WORKER
    worker_id: str
    mode: str


class DownloadModelPayload(_Payload):
    job_type: Literal[JobType.DOWNLOAD_MODEL_ON_WORKER] = JobType.DOWNLOAD_MODEL_ON_WORKER
    mode: str


JobPayload = (
    GeneratePayload | ScorePayload | LoraTrainingPayload | LoadModelPayload | DownloadModelPayload
)

JOB_PAYLOAD_ADAPTER: TypeAdapter[JobPayload] = TypeAdapter(
    Annotated[JobPayload, Field(discriminator="job_type")]
)
