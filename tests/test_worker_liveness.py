"""Tests for the job-type ownership of worker liveness signals."""

from songmaker_cli.constants import JobType
from songmaker_cli.worker_liveness import WorkerLiveness, worker_liveness_by_job_type


def test_worker_liveness_maps_each_job_type_to_its_real_execution_signal() -> None:
    liveness = worker_liveness_by_job_type(
        acestep=WorkerLiveness.ALIVE,
        music=WorkerLiveness.DEAD,
        scoring=WorkerLiveness.UNKNOWN,
    )

    assert liveness == {
        JobType.GENERATE: WorkerLiveness.ALIVE,
        JobType.LOAD_MODEL_ON_WORKER: WorkerLiveness.ALIVE,
        JobType.DOWNLOAD_MODEL_ON_WORKER: WorkerLiveness.ALIVE,
        JobType.LORA_TRAINING: WorkerLiveness.DEAD,
        JobType.SCORE: WorkerLiveness.UNKNOWN,
        JobType.CHAT: WorkerLiveness.UNKNOWN,
    }
