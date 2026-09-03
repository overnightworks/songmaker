"""Worker-liveness policy shared by lifecycle reaping and its callers."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from songmaker_cli.constants import JobType


class WorkerLiveness(StrEnum):
    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


def worker_liveness_by_job_type(
    *,
    acestep: WorkerLiveness,
    music: WorkerLiveness,
    scoring: WorkerLiveness,
) -> dict[JobType, WorkerLiveness]:
    """Return the real execution-worker signal for every job type."""
    return {
        JobType.GENERATE: acestep,
        JobType.LOAD_MODEL_ON_WORKER: acestep,
        JobType.DOWNLOAD_MODEL_ON_WORKER: acestep,
        JobType.LORA_TRAINING: music,
        JobType.SCORE: scoring,
        JobType.CHAT: WorkerLiveness.UNKNOWN,
    }


def liveness_for_job_type(
    job_type: JobType,
    liveness_by_type: Mapping[JobType, WorkerLiveness] | None,
) -> WorkerLiveness:
    if liveness_by_type is None:
        return WorkerLiveness.UNKNOWN
    return liveness_by_type.get(job_type, WorkerLiveness.UNKNOWN)
