"""Job timing: heartbeat and queue thresholds, the stale-job policy table, restart grace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from acestep_engine.settings import get_engine_settings
from songmaker_cli.job_types import JobType, WorkerLivenessSignal

WORKER_RESTART_GRACE_SECONDS: Final[int] = 300
"""Container restart, including the 30-second healthcheck start period, plus reserve."""
GENERATE_LOAD_MODEL_TIMEOUT_SECONDS: Final[int] = 600
GENERATE_SUBMIT_TIMEOUT_SECONDS: Final[int] = 30
GPU_HOLD_POLL_INTERVAL_SECONDS: Final[int] = 5
ACESTEP_SSE_CONNECT_TIMEOUT_SECONDS: Final[int] = 10
ACESTEP_SSE_READ_TIMEOUT_MARGIN_SECONDS: Final[int] = 30


def acestep_sse_read_timeout_seconds(poll_timeout: float) -> int:
    """Return the SSE read timeout for one configured polling interval."""
    return int(poll_timeout) + ACESTEP_SSE_READ_TIMEOUT_MARGIN_SECONDS


ACESTEP_SSE_READ_TIMEOUT_SECONDS: Final[int] = acestep_sse_read_timeout_seconds(
    get_engine_settings().acestep_poll_timeout,
)
QUEUED_JOB_STALE_THRESHOLD_SECONDS: Final[int] = 900
WORKER_JOB_QUEUED_STALE_THRESHOLD_SECONDS: Final[int] = 1100
JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS: Final[int] = 180
COVER_JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS: Final[int] = 120
JOB_HEARTBEAT_INTERVAL_SECONDS: Final[int] = 15
# These are not independently configurable timeouts. They document the
# measured/provisioned liveness bounds that feed STALE_JOB_THRESHOLDS below.
LORA_TRAINING_HEARTBEAT_STALE_THRESHOLD_SECONDS: Final[int] = 300
SCORE_JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS: Final[int] = 600
JOB_REAPER_INTERVAL_SECONDS: Final[int] = 120
GENERATE_JOB_HEARTBEAT_TICK_RESERVE_SECONDS: Final[int] = JOB_REAPER_INTERVAL_SECONDS
GENERATE_PRE_FIRST_EVENT_TIMEOUT_SECONDS: Final[int] = (
    GENERATE_LOAD_MODEL_TIMEOUT_SECONDS
    + GENERATE_SUBMIT_TIMEOUT_SECONDS
    + ACESTEP_SSE_CONNECT_TIMEOUT_SECONDS
)


def generate_job_heartbeat_stale_threshold_seconds(sse_read_timeout_seconds: int) -> int:
    """Return the generate heartbeat bound for one configured SSE read window."""
    return (
        max(GENERATE_PRE_FIRST_EVENT_TIMEOUT_SECONDS, sse_read_timeout_seconds)
        + GENERATE_JOB_HEARTBEAT_TICK_RESERVE_SECONDS
    )


GENERATE_JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS: Final[int] = (
    generate_job_heartbeat_stale_threshold_seconds(ACESTEP_SSE_READ_TIMEOUT_SECONDS)
)
LOAD_MODEL_JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS: Final[int] = 1300
DOWNLOAD_MODEL_JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS: Final[int] = 180


@dataclass(frozen=True)
class JobStaleThresholds:
    """Maximum inactive time for a queued or running job type.

    A queued job uses its execution worker's signal. Unknown signals use the
    queued-age guard; an alive signal instead permits one whole queue's worth
    of running-heartbeat windows.
    """

    queued_seconds: int
    heartbeat_seconds: int
    liveness_signal: WorkerLivenessSignal | None
    restart_grace_seconds: int | None

    def full_queue_bound_seconds(self, max_queue_depth: int) -> int:
        """Return the longest queue wait: depth times this type's running bound.

        At most ``max_queue_depth`` jobs can precede a queued job, and each can
        consume one running-heartbeat threshold before the reaper intervenes.
        """
        return max_queue_depth * self.heartbeat_seconds


# The one stale-job policy. Each heartbeat threshold is derived from the
# slowest measured or provisioned progress signal for that type; see #331 F20.
STALE_JOB_THRESHOLDS: Final[dict[JobType, JobStaleThresholds]] = {
    JobType.COVER: JobStaleThresholds(
        queued_seconds=QUEUED_JOB_STALE_THRESHOLD_SECONDS,
        heartbeat_seconds=COVER_JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS,
        liveness_signal=None,
        restart_grace_seconds=None,
    ),  # runs in the web process, which has no worker liveness signal
    JobType.CHAT: JobStaleThresholds(
        queued_seconds=QUEUED_JOB_STALE_THRESHOLD_SECONDS,
        heartbeat_seconds=JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS,
        liveness_signal=None,
        restart_grace_seconds=None,
    ),  # chat timer: 15 s; twelve missed intervals
    JobType.LORA_TRAINING: JobStaleThresholds(
        queued_seconds=WORKER_JOB_QUEUED_STALE_THRESHOLD_SECONDS,
        heartbeat_seconds=LORA_TRAINING_HEARTBEAT_STALE_THRESHOLD_SECONDS,
        liveness_signal=WorkerLivenessSignal.MUSIC,
        restart_grace_seconds=WORKER_RESTART_GRACE_SECONDS,
    ),  # measured train_lora heartbeat: <= 60 s, with five intervals' margin
    JobType.SCORE: JobStaleThresholds(
        queued_seconds=WORKER_JOB_QUEUED_STALE_THRESHOLD_SECONDS,
        heartbeat_seconds=SCORE_JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS,
        liveness_signal=WorkerLivenessSignal.SCORING,
        restart_grace_seconds=WORKER_RESTART_GRACE_SECONDS,
    ),  # 300 s scorer, then safety margin (#331 F20)
    JobType.GENERATE: JobStaleThresholds(
        queued_seconds=WORKER_JOB_QUEUED_STALE_THRESHOLD_SECONDS,
        heartbeat_seconds=GENERATE_JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS,
        liveness_signal=WorkerLivenessSignal.MODEL_EXECUTION,
        restart_grace_seconds=WORKER_RESTART_GRACE_SECONDS,
    ),  # max(load + submit + connect, SSE read) plus one reaper tick
    JobType.LOAD_MODEL_ON_WORKER: JobStaleThresholds(
        queued_seconds=WORKER_JOB_QUEUED_STALE_THRESHOLD_SECONDS,
        heartbeat_seconds=LOAD_MODEL_JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS,
        liveness_signal=WorkerLivenessSignal.MODEL_EXECUTION,
        restart_grace_seconds=WORKER_RESTART_GRACE_SECONDS,
    ),  # 960 s worker request timeout plus margin; no progress signal exists
    JobType.DOWNLOAD_MODEL_ON_WORKER: JobStaleThresholds(
        queued_seconds=WORKER_JOB_QUEUED_STALE_THRESHOLD_SECONDS,
        heartbeat_seconds=DOWNLOAD_MODEL_JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS,
        liveness_signal=WorkerLivenessSignal.MODEL_EXECUTION,
        restart_grace_seconds=WORKER_RESTART_GRACE_SECONDS,
    ),  # worker polls download progress every 2 s; 180 s tolerates 90 misses
}


def worker_restart_grace_seconds(signal: WorkerLivenessSignal) -> int:
    """Return the one restart grace declared for an execution signal."""
    grace_seconds = {
        threshold.restart_grace_seconds
        for threshold in STALE_JOB_THRESHOLDS.values()
        if threshold.liveness_signal is signal
    }
    if len(grace_seconds) != 1 or None in grace_seconds:
        raise RuntimeError(f"No single restart grace configured for {signal}")
    return grace_seconds.pop()
