"""API models for background jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from typing import Final, Literal

from pydantic import BaseModel

from songmaker_cli.constants import GENERATION_ETA_MIN_PROGRESS
from songmaker_cli.invariants import expect_present
from songmaker_cli.job_types import JOB_TERMINAL_STATUSES, GenerationPhase, JobStatus, JobType
from songmaker_cli.messages import Message, stored_sentence
from songmaker_cli.words import SOURCE_LANGUAGE, text

REMAINING_TIME_ESTIMATE_CALCULATING: Final = "calculating"
RemainingTimeEstimate = int | Literal["calculating"]


def _remaining_time_estimate(
    job,
    *,
    now: datetime,
) -> RemainingTimeEstimate:
    if job.status in JOB_TERMINAL_STATUSES:
        return 0
    if job.status != JobStatus.RUNNING:
        return REMAINING_TIME_ESTIMATE_CALCULATING
    if job.type == JobType.GENERATE:
        return _generation_remaining_time(job, now=now)
    return _training_remaining_time(job, now=now)


def _generation_remaining_time(job, *, now: datetime) -> RemainingTimeEstimate:
    if job.progress >= 1:
        return 0
    if job.progress < GENERATION_ETA_MIN_PROGRESS or job.generation_started_at is None:
        return REMAINING_TIME_ESTIMATE_CALCULATING
    elapsed_seconds = (now - job.generation_started_at).total_seconds()
    if elapsed_seconds <= 0:
        return REMAINING_TIME_ESTIMATE_CALCULATING
    return ceil(elapsed_seconds * (1 - job.progress) / job.progress)


def _training_remaining_time(job, *, now: datetime) -> RemainingTimeEstimate:
    current_epoch = job.current_epoch
    train_epochs = job.train_epochs
    if current_epoch is None or train_epochs is None:
        return REMAINING_TIME_ESTIMATE_CALCULATING
    if current_epoch <= 0 or train_epochs < current_epoch:
        return REMAINING_TIME_ESTIMATE_CALCULATING
    if job.training_started_at is None:
        return REMAINING_TIME_ESTIMATE_CALCULATING
    elapsed_seconds = (now - job.training_started_at).total_seconds()
    if elapsed_seconds <= 0:
        return REMAINING_TIME_ESTIMATE_CALCULATING
    seconds_per_epoch = elapsed_seconds / current_epoch
    return ceil(seconds_per_epoch * (train_epochs - current_epoch))


def _failure_sentence(job) -> str | None:
    """The agent's sentence of a job's failure: its cause, led by a partial Generate's takes."""
    cause = stored_sentence(job.error_message, f"Job {job.id} failure")
    if cause is None or job.completed_takes is None:
        return cause
    count = expect_present(job.take_count, f"Job {job.id} completed takes without a take count")
    return text(
        SOURCE_LANGUAGE,
        "jobFailure.partialTakes",
        count=count,
        completed=str(job.completed_takes),
        failed=str(count - job.completed_takes),
        cause=cause,
    )


class JobResponse(BaseModel):
    id: str
    type: JobType
    status: str
    version_id: str | None = None
    progress: float = 0.0
    phase: GenerationPhase | None = None
    take_index: int | None = None
    take_count: int | None = None
    current_epoch: int | None = None
    train_epochs: int | None = None
    remaining_time_estimate: RemainingTimeEstimate | None = None
    completed_takes: int | None = None
    error: str | None = None
    error_message: Message | None = None
    error_type: str | None = None
    retry_after_seconds: int | None = None
    queue_reason: str | None = None
    queue_reason_message: Message | None = None
    queue_position: int | None = None
    started_at: str | None = None
    completed_at: str | None = None

    @classmethod
    def from_orm(
        cls,
        job,
        queue_position: int | None = None,
        *,
        now: datetime | None = None,
    ) -> JobResponse:
        now = now or datetime.now(timezone.utc)
        return cls(
            id=job.id,
            type=job.type,
            status=job.status,
            version_id=job.version_id,
            progress=job.progress,
            phase=job.phase if job.status == JobStatus.RUNNING else None,
            take_index=job.take_index,
            take_count=job.take_count,
            current_epoch=job.current_epoch,
            train_epochs=job.train_epochs,
            remaining_time_estimate=_remaining_time_estimate(job, now=now),
            completed_takes=job.completed_takes,
            error=_failure_sentence(job),
            error_message=job.error_message,
            error_type=job.error_type,
            retry_after_seconds=job.retry_after_seconds,
            queue_reason=stored_sentence(job.queue_reason_message, f"Job {job.id} queue wait"),
            queue_reason_message=job.queue_reason_message,
            queue_position=queue_position,
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
        )


class GenerationUnavailableResponse(BaseModel):
    detail: str
    message: Message
    error_type: str
    job_id: str
