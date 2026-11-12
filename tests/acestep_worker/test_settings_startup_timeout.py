"""The ACE-Step startup timeout ends before the scheduler gives up on the model load."""

from __future__ import annotations

from acestep_worker.settings import WorkerSettings
from songmaker_cli.job_timing import GENERATE_LOAD_MODEL_TIMEOUT_SECONDS


def test_the_default_startup_timeout_ends_before_the_scheduler_gives_up() -> None:
    settings = WorkerSettings(
        worker_id="w", redis_url="redis://fake", songmaker_internal_token="t",
    )
    eviction_seconds = (
        settings.acestep_shutdown_grace_seconds + settings.acestep_shutdown_kill_seconds
    )

    assert (
        settings.acestep_startup_timeout_seconds + eviction_seconds
        < GENERATE_LOAD_MODEL_TIMEOUT_SECONDS
    )
