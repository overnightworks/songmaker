"""API models for background jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from typing import Final, Literal

from pydantic import BaseModel

from songmaker_cli.constants import JOB_TERMINAL_STATUSES, JobStatus

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

    current_epoch = job.current_epoch
    train_epochs = job.train_epochs
    if (
        current_epoch is None
        or train_epochs is None
        or current_epoch <= 0
        or train_epochs <= current_epoch
    ):
        if (
            train_epochs is not None
            and current_epoch is not None
            and train_epochs == current_epoch
        ):
            return 0
        return REMAINING_TIME_ESTIMATE_CALCULATING

    training_started_at = job.training_started_at
    if training_started_at is None:
        return REMAINING_TIME_ESTIMATE_CALCULATING
    if training_started_at.tzinfo is None:
        training_started_at = training_started_at.replace(tzinfo=timezone.utc)
    elapsed_seconds = (now - training_started_at).total_seconds()
    if elapsed_seconds <= 0:
        return REMAINING_TIME_ESTIMATE_CALCULATING

    seconds_per_epoch = elapsed_seconds / current_epoch
    return ceil(seconds_per_epoch * (train_epochs - current_epoch))


class JobResponse(BaseModel):
    id: str
    type: str
    status: str
    progress: float = 0.0
    current_epoch: int | None = None
    train_epochs: int | None = None
    remaining_time_estimate: RemainingTimeEstimate | None = None
    error: str | None = None
    error_type: str | None = None
    queue_reason: str | None = None
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
            progress=job.progress,
            current_epoch=job.current_epoch,
            train_epochs=job.train_epochs,
            remaining_time_estimate=_remaining_time_estimate(job, now=now),
            error=job.error,
            error_type=job.error_type,
            queue_reason=job.queue_reason,
            queue_position=queue_position,
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
        )
