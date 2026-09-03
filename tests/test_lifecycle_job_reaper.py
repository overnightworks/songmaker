"""Tests for the lifecycle-owned stale-job reaper and LoRA reconciliation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import TEST_SECRET, make_fake_redis

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import (
    BACKGROUND_LOOP_FAILURE_THRESHOLD,
    JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS,
    QUEUED_JOB_STALE_THRESHOLD_SECONDS,
    STALE_JOB_THRESHOLDS,
    JobStatus,
    JobType,
    LoraStatus,
)
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Job, User, UserLora
from songmaker_cli.db.queries import get_user_lora
from songmaker_cli.lifecycle import (
    BackgroundLoopName,
    BackgroundLoopRegistry,
    BackgroundLoopStatus,
    _run_stale_job_reaper_tick,
    reap_stale_jobs,
    stale_job_reaper_loop,
)
from songmaker_cli.settings import get_settings
from songmaker_cli.worker_liveness import WorkerLiveness


@pytest.fixture()
def ctx(tmp_path: Path) -> AppContext:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    factory = init_test_db(tmp_path / "songmaker.db")
    return AppContext(
        db=factory, audio_dir=audio_dir, data_dir=tmp_path / "data",
        session_secret=TEST_SECRET, redis=make_fake_redis(),
    )


def _dead_process_time(now: datetime, threshold_seconds: int) -> datetime:
    """A timestamp old enough that its owning process looks dead."""
    return now - timedelta(seconds=threshold_seconds + 60)


def _add_job(
    ctx: AppContext, *, job_id: str, job_type: str, status: str,
    started_at: datetime | None = None, heartbeat_at: datetime | None = None,
) -> None:
    with ctx.db() as session:
        kwargs = {}
        if started_at is not None:
            kwargs["started_at"] = started_at
        if heartbeat_at is not None:
            kwargs["heartbeat_at"] = heartbeat_at
        session.add(Job(id=job_id, type=job_type, status=status, **kwargs))
        session.commit()


def _job_status(ctx: AppContext, job_id: str) -> str:
    with ctx.db() as session:
        return session.query(Job).filter_by(id=job_id).first().status


class TestLifecycleReaper:
    def test_fails_an_old_queued_chat_job_when_no_worker_signal_exists(self, ctx) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        dead = _dead_process_time(now, QUEUED_JOB_STALE_THRESHOLD_SECONDS)
        _add_job(
            ctx, job_id="chat-1", job_type=JobType.CHAT, status=JobStatus.QUEUED,
            started_at=dead, heartbeat_at=dead,
        )

        recovered = reap_stale_jobs(ctx, now=now)

        assert recovered == 1
        with ctx.db() as session:
            job = session.query(Job).filter_by(id="chat-1").one()
            assert job.status == JobStatus.FAILED
            assert job.error == "Queued too long — please retry."
            assert job.error_type == "queued_too_long"

    def test_fails_a_silenced_running_chat_job_by_heartbeat(self, ctx) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        dead = _dead_process_time(now, JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS)
        _add_job(
            ctx, job_id="chat-running", job_type=JobType.CHAT,
            status=JobStatus.RUNNING, started_at=now, heartbeat_at=dead,
        )

        recovered = reap_stale_jobs(ctx, now=now)

        assert recovered == 1
        with ctx.db() as session:
            job = session.query(Job).filter_by(id="chat-running").one()
            assert job.status == JobStatus.FAILED
            assert job.error == "Heartbeat lost — please retry."
            assert job.error_type == "heartbeat_lost"

    def test_leaves_a_fresh_chat_job_alone(self, ctx) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        _add_job(
            ctx, job_id="chat-2", job_type=JobType.CHAT, status=JobStatus.RUNNING,
            started_at=now, heartbeat_at=now,
        )

        recovered = reap_stale_jobs(ctx, now=now)

        assert recovered == 0
        assert _job_status(ctx, "chat-2") == JobStatus.RUNNING

    def test_reaps_other_job_types_from_the_same_table(self, ctx) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        dead = _dead_process_time(
            now, STALE_JOB_THRESHOLDS[JobType.GENERATE].heartbeat_seconds,
        )
        _add_job(
            ctx, job_id="gen-1", job_type=JobType.GENERATE, status=JobStatus.RUNNING,
            started_at=dead, heartbeat_at=dead,
        )

        recovered = reap_stale_jobs(ctx, now=now)

        assert recovered == 1
        assert _job_status(ctx, "gen-1") == JobStatus.FAILED

    @pytest.mark.parametrize("job_type", (
        JobType.GENERATE, JobType.LOAD_MODEL_ON_WORKER,
        JobType.DOWNLOAD_MODEL_ON_WORKER, JobType.LORA_TRAINING, JobType.SCORE,
    ))
    def test_known_dead_worker_reaps_a_queued_job_without_using_job_age(
        self, ctx, job_type: JobType,
    ) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        _add_job(
            ctx, job_id=f"{job_type}-queued-dead", job_type=job_type,
            status=JobStatus.QUEUED, started_at=now, heartbeat_at=now,
        )

        recovered = reap_stale_jobs(
            ctx,
            now=now,
            worker_liveness={job_type: WorkerLiveness.DEAD},
        )

        assert recovered == 1
        with ctx.db() as session:
            job = session.query(Job).filter_by(id=f"{job_type}-queued-dead").one()
            assert job.error_type == "no_worker_alive"
            assert job.error == "No worker alive for this job type — please retry."

    @pytest.mark.parametrize("job_type", tuple(JobType))
    def test_unknown_queued_age_guard_applies_for_every_job_type(
        self, ctx, job_type: JobType,
    ) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        thresholds = STALE_JOB_THRESHOLDS[job_type]
        _add_job(
            ctx, job_id=f"{job_type}-queued-old", job_type=job_type,
            status=JobStatus.QUEUED,
            started_at=now - timedelta(
                seconds=thresholds.queued_seconds + 1,
            ),
            heartbeat_at=now,
        )

        recovered = reap_stale_jobs(
            ctx,
            now=now,
            worker_liveness={job_type: WorkerLiveness.UNKNOWN},
        )

        assert recovered == 1
        with ctx.db() as session:
            job = session.query(Job).filter_by(id=f"{job_type}-queued-old").one()
            assert job.error == "Queued too long — please retry."
            assert job.error_type == "queued_too_long"

    @pytest.mark.parametrize(
        "job_type",
        (
            JobType.GENERATE,
            JobType.LOAD_MODEL_ON_WORKER,
            JobType.DOWNLOAD_MODEL_ON_WORKER,
            JobType.LORA_TRAINING,
            JobType.SCORE,
        ),
    )
    def test_alive_queued_job_ignores_the_unknown_age_guard_until_a_full_queue(
        self, ctx, job_type: JobType,
    ) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        thresholds = STALE_JOB_THRESHOLDS[job_type]
        full_queue_bound = thresholds.full_queue_bound_seconds(get_settings().max_queue_depth)
        _add_job(
            ctx, job_id=f"{job_type}-queued-alive", job_type=job_type,
            status=JobStatus.QUEUED,
            started_at=now - timedelta(seconds=thresholds.queued_seconds + 1), heartbeat_at=now,
        )

        recovered = reap_stale_jobs(
            ctx,
            now=now,
            worker_liveness={job_type: WorkerLiveness.ALIVE},
        )

        assert recovered == 0
        assert _job_status(ctx, f"{job_type}-queued-alive") == JobStatus.QUEUED

        with ctx.db() as session:
            job = session.query(Job).filter_by(id=f"{job_type}-queued-alive").one()
            job.started_at = now - timedelta(seconds=full_queue_bound + 1)
            session.commit()

        assert reap_stale_jobs(
            ctx, now=now, worker_liveness={job_type: WorkerLiveness.ALIVE},
        ) == 1
        with ctx.db() as session:
            job = session.query(Job).filter_by(id=f"{job_type}-queued-alive").one()
            assert job.error == "Queued longer than a full queue could take — please retry."
            assert job.error_type == "queued_full_queue_bound"

    def test_queued_chat_ignores_an_injected_dead_worker_before_its_age_guard(self, ctx) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        _add_job(
            ctx, job_id="chat-queued-dead", job_type=JobType.CHAT,
            status=JobStatus.QUEUED, started_at=now, heartbeat_at=now,
        )

        recovered = reap_stale_jobs(
            ctx,
            now=now,
            worker_liveness={JobType.CHAT: WorkerLiveness.DEAD},
        )

        assert recovered == 0
        assert _job_status(ctx, "chat-queued-dead") == JobStatus.QUEUED


def test_reaper_policy_failure_is_recorded_for_health(ctx, monkeypatch) -> None:
    """Missing policy rows fail the lifecycle loop instead of hiding active jobs."""
    registry = BackgroundLoopRegistry()
    app = SimpleNamespace(
        state=SimpleNamespace(
            ctx=SimpleNamespace(
                db=ctx.db,
                redis=SimpleNamespace(
                    exists=lambda *_args, **_kwargs: False,
                    get=lambda *_args, **_kwargs: None,
                    set=lambda *_args, **_kwargs: True,
                ),
            ),
            background_loop_registry=registry,
        ),
    )
    _add_job(ctx, job_id="missing-policy", job_type="unknown_type", status=JobStatus.QUEUED)
    completed_ticks = 0

    async def fake_sleep(_seconds: float) -> None:
        nonlocal completed_ticks
        if completed_ticks == BACKGROUND_LOOP_FAILURE_THRESHOLD:
            raise asyncio.CancelledError()
        completed_ticks += 1

    monkeypatch.setattr("songmaker_cli.lifecycle.asyncio.sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(stale_job_reaper_loop(app))

    health = registry.loop_health()[BackgroundLoopName.STALE_JOB_REAPER]
    assert health.status is BackgroundLoopStatus.FAILING
    assert health.consecutive_failures == BACKGROUND_LOOP_FAILURE_THRESHOLD
    assert health.last_error == "RuntimeError"


class TestLoraTrainingThreshold:
    def test_terminal_izes_a_lora_training_job_whose_worker_died(self, ctx) -> None:
        now = datetime.now(timezone.utc)
        dead = _dead_process_time(
            now, STALE_JOB_THRESHOLDS[JobType.LORA_TRAINING].heartbeat_seconds,
        )
        _add_job(
            ctx, job_id="lora-1", job_type=JobType.LORA_TRAINING, status=JobStatus.RUNNING,
            started_at=dead, heartbeat_at=dead,
        )

        recovered = reap_stale_jobs(ctx, now=now)

        assert recovered == 1
        assert _job_status(ctx, "lora-1") == JobStatus.FAILED

    def test_leaves_a_recently_heartbeating_job_running(self, ctx) -> None:
        """A long-running but alive job (recent heartbeat) must survive —
        lora_training jobs can legitimately run far longer than the age
        cutoff alone would tolerate."""
        now = datetime.now(timezone.utc)
        old_start = _dead_process_time(
            now, STALE_JOB_THRESHOLDS[JobType.LORA_TRAINING].heartbeat_seconds,
        )
        _add_job(
            ctx, job_id="lora-2", job_type=JobType.LORA_TRAINING, status=JobStatus.RUNNING,
            started_at=old_start, heartbeat_at=now,
        )

        recovered = reap_stale_jobs(ctx, now=now)

        assert recovered == 0
        assert _job_status(ctx, "lora-2") == JobStatus.RUNNING


def test_reaper_tick_reaps_chat_and_resolves_the_lora_reconciliation_loop(ctx) -> None:
    """One tick closes both loops: a dead chat job goes terminal, and a dead
    lora_training job goes terminal *and* unblocks reconcile_crashed_loras,
    which previously waited forever on a job nothing ever terminal-izes."""
    now = datetime.now(timezone.utc)
    chat_dead = _dead_process_time(now, QUEUED_JOB_STALE_THRESHOLD_SECONDS)
    lora_dead = _dead_process_time(
        now, STALE_JOB_THRESHOLDS[JobType.LORA_TRAINING].heartbeat_seconds,
    )
    _add_job(
        ctx, job_id="chat-3", job_type=JobType.CHAT, status=JobStatus.QUEUED,
        started_at=chat_dead, heartbeat_at=chat_dead,
    )
    _add_job(
        ctx, job_id="lora-3", job_type=JobType.LORA_TRAINING, status=JobStatus.RUNNING,
        started_at=lora_dead, heartbeat_at=lora_dead,
    )
    with ctx.db() as session:
        session.add(User(id="u1", username="u1", password_hash="x"))
        session.add(
            UserLora(
                id="L-tick", user_id="u1", name="L-tick", slug="L-tick",
                status=LoraStatus.TRAINING, training_job_id="lora-3",
            ),
        )
        session.commit()

    recovered_jobs, reconciled_loras = _run_stale_job_reaper_tick(ctx, now=now)

    assert recovered_jobs == 2
    assert reconciled_loras == 1
    assert _job_status(ctx, "chat-3") == JobStatus.FAILED
    assert _job_status(ctx, "lora-3") == JobStatus.FAILED
    with ctx.db() as s:
        assert get_user_lora(s, "L-tick", include_deleted_rows=True).status == LoraStatus.FAILED
