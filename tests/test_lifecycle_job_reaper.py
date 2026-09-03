"""Tests for lifecycle.reap_stale_chat_jobs / reap_stale_lora_training_jobs /
_run_stale_job_reaper_tick — the chat and lora_training equivalent of
WorkerBase's arq-worker cron for generate/score (issue #371).

chat runs inline in a web request and lora_training shares MusicWorker's
process with generate but is excluded from its job_type-scoped recovery, so
neither ever leaves QUEUED/RUNNING on its own when its process dies. These
tests simulate that death directly: a job stuck active with a stale
started_at/heartbeat_at, exactly as a killed process would leave it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import TEST_SECRET, make_fake_redis

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import (
    JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS,
    QUEUED_JOB_STALE_THRESHOLD_SECONDS,
    JobStatus,
    JobType,
    LoraStatus,
)
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Job, User, UserLora
from songmaker_cli.db.queries import get_user_lora
from songmaker_cli.lifecycle import (
    _run_stale_job_reaper_tick,
    reap_stale_chat_jobs,
    reap_stale_lora_training_jobs,
)
from songmaker_cli.settings import get_settings


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


class TestReapStaleChatJobs:
    def test_fails_a_queued_chat_job_when_no_worker_starts_it(self, ctx) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        dead = _dead_process_time(now, QUEUED_JOB_STALE_THRESHOLD_SECONDS)
        _add_job(
            ctx, job_id="chat-1", job_type=JobType.CHAT, status=JobStatus.QUEUED,
            started_at=dead, heartbeat_at=dead,
        )

        recovered = reap_stale_chat_jobs(ctx, now=now)

        assert recovered == 1
        with ctx.db() as session:
            job = session.query(Job).filter_by(id="chat-1").one()
            assert job.status == JobStatus.FAILED
            assert job.error == "No worker available — please retry."
            assert job.error_type == "no_worker_available"

    def test_fails_a_silenced_running_chat_job_by_heartbeat(self, ctx) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        dead = _dead_process_time(now, JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS)
        _add_job(
            ctx, job_id="chat-running", job_type=JobType.CHAT,
            status=JobStatus.RUNNING, started_at=now, heartbeat_at=dead,
        )

        recovered = reap_stale_chat_jobs(ctx, now=now)

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

        recovered = reap_stale_chat_jobs(ctx, now=now)

        assert recovered == 0
        assert _job_status(ctx, "chat-2") == JobStatus.RUNNING

    def test_ignores_other_job_types(self, ctx) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        dead = _dead_process_time(now, QUEUED_JOB_STALE_THRESHOLD_SECONDS)
        _add_job(
            ctx, job_id="gen-1", job_type=JobType.GENERATE, status=JobStatus.RUNNING,
            started_at=dead, heartbeat_at=dead,
        )

        recovered = reap_stale_chat_jobs(ctx, now=now)

        assert recovered == 0
        assert _job_status(ctx, "gen-1") == JobStatus.RUNNING


class TestReapStaleLoraTrainingJobs:
    def test_terminal_izes_a_lora_training_job_whose_worker_died(self, ctx) -> None:
        dead = _dead_process_time(
            datetime.now(timezone.utc), get_settings().stale_job_threshold_seconds,
        )
        _add_job(
            ctx, job_id="lora-1", job_type=JobType.LORA_TRAINING, status=JobStatus.RUNNING,
            started_at=dead, heartbeat_at=dead,
        )

        recovered = reap_stale_lora_training_jobs(ctx)

        assert recovered == 1
        assert _job_status(ctx, "lora-1") == JobStatus.FAILED

    def test_leaves_a_recently_heartbeating_job_running(self, ctx) -> None:
        """A long-running but alive job (recent heartbeat) must survive —
        lora_training jobs can legitimately run far longer than the age
        cutoff alone would tolerate."""
        old_start = _dead_process_time(
            datetime.now(timezone.utc), get_settings().stale_job_threshold_seconds,
        )
        _add_job(
            ctx, job_id="lora-2", job_type=JobType.LORA_TRAINING, status=JobStatus.RUNNING,
            started_at=old_start, heartbeat_at=datetime.now(timezone.utc),
        )

        recovered = reap_stale_lora_training_jobs(ctx)

        assert recovered == 0
        assert _job_status(ctx, "lora-2") == JobStatus.RUNNING


def test_reaper_tick_reaps_chat_and_resolves_the_lora_reconciliation_loop(ctx) -> None:
    """One tick closes both loops: a dead chat job goes terminal, and a dead
    lora_training job goes terminal *and* unblocks reconcile_crashed_loras,
    which previously waited forever on a job nothing ever terminal-izes."""
    now = datetime.now(timezone.utc)
    chat_dead = _dead_process_time(now, QUEUED_JOB_STALE_THRESHOLD_SECONDS)
    lora_dead = _dead_process_time(now, get_settings().stale_job_threshold_seconds)
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

    recovered_chat, reconciled_loras = _run_stale_job_reaper_tick(ctx)

    assert recovered_chat == 1
    assert reconciled_loras == 1
    assert _job_status(ctx, "chat-3") == JobStatus.FAILED
    assert _job_status(ctx, "lora-3") == JobStatus.FAILED
    with ctx.db() as s:
        assert get_user_lora(s, "L-tick", include_deleted_rows=True).status == LoraStatus.FAILED
