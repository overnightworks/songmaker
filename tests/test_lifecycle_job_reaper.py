"""Tests for lifecycle's shared stale-job reaper (issue #371)."""

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
    reap_stale_jobs,
)
from songmaker_cli.settings import get_settings


@pytest.fixture()
def ctx(tmp_path: Path) -> AppContext:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    factory = init_test_db(tmp_path / "songmaker.db")
    return AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )


_NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _dead_process_time(threshold_seconds: int) -> datetime:
    """A timestamp old enough that its owning process looks dead."""
    return _NOW - timedelta(seconds=threshold_seconds + 60)


def _add_job(
    ctx: AppContext,
    *,
    job_id: str,
    job_type: str,
    status: str,
    started_at: datetime | None = None,
    heartbeat_at: datetime | None = None,
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


class TestReapStaleJobs:
    def test_terminal_izes_a_queued_job_without_a_worker(self, ctx) -> None:
        dead = _dead_process_time(QUEUED_JOB_STALE_THRESHOLD_SECONDS)
        _add_job(
            ctx,
            job_id="chat-1",
            job_type=JobType.CHAT,
            status=JobStatus.QUEUED,
            started_at=dead,
            heartbeat_at=dead,
        )

        recovered = reap_stale_jobs(ctx, now=_NOW)

        assert recovered == 1
        with ctx.db() as session:
            job = session.query(Job).filter_by(id="chat-1").one()
            assert job.status == JobStatus.FAILED
            assert job.error_type == "no_worker_available"

    def test_marks_a_running_chat_with_a_stale_heartbeat_as_failed(self, ctx) -> None:
        dead = _dead_process_time(JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS)
        _add_job(
            ctx,
            job_id="chat-running",
            job_type=JobType.CHAT,
            status=JobStatus.RUNNING,
            started_at=_NOW,
            heartbeat_at=dead,
        )

        recovered = reap_stale_jobs(ctx, now=_NOW)

        assert recovered == 1
        with ctx.db() as session:
            job = session.query(Job).filter_by(id="chat-running").first()
            assert job.status == JobStatus.FAILED
            assert job.error == "Heartbeat abgerissen — bitte erneut versuchen."
            assert job.error_type == "heartbeat_lost"

    def test_leaves_a_fresh_chat_job_alone(self, ctx) -> None:
        _add_job(
            ctx,
            job_id="chat-2",
            job_type=JobType.CHAT,
            status=JobStatus.RUNNING,
            started_at=_NOW,
            heartbeat_at=_NOW,
        )

        recovered = reap_stale_jobs(ctx, now=_NOW)

        assert recovered == 0
        assert _job_status(ctx, "chat-2") == JobStatus.RUNNING

    def test_uses_the_age_threshold_for_non_periodic_job_heartbeats(self, ctx) -> None:
        dead = _dead_process_time(get_settings().stale_job_threshold_seconds)
        for job_type in (JobType.GENERATE, JobType.SCORE, JobType.LORA_TRAINING):
            _add_job(
                ctx,
                job_id=f"{job_type}-old",
                job_type=job_type,
                status=JobStatus.RUNNING,
                started_at=dead,
                heartbeat_at=dead,
            )

        recovered = reap_stale_jobs(ctx, now=_NOW)

        assert recovered == 3
        for job_type in (JobType.GENERATE, JobType.SCORE, JobType.LORA_TRAINING):
            assert _job_status(ctx, f"{job_type}-old") == JobStatus.FAILED

    def test_keeps_non_periodic_jobs_running_before_their_age_threshold(self, ctx) -> None:
        stale_for_chat = _dead_process_time(JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS)
        for job_type in (JobType.GENERATE, JobType.SCORE, JobType.LORA_TRAINING):
            _add_job(
                ctx,
                job_id=f"{job_type}-alive",
                job_type=job_type,
                status=JobStatus.RUNNING,
                started_at=stale_for_chat,
                heartbeat_at=stale_for_chat,
            )

        recovered = reap_stale_jobs(ctx, now=_NOW)

        assert recovered == 0
        for job_type in (JobType.GENERATE, JobType.SCORE, JobType.LORA_TRAINING):
            assert _job_status(ctx, f"{job_type}-alive") == JobStatus.RUNNING


def test_reaper_tick_reaps_chat_and_resolves_the_lora_reconciliation_loop(ctx) -> None:
    """One tick terminalizes jobs before it reconciles their LoRA row."""
    chat_dead = _dead_process_time(QUEUED_JOB_STALE_THRESHOLD_SECONDS)
    lora_dead = _dead_process_time(get_settings().stale_job_threshold_seconds)
    _add_job(
        ctx,
        job_id="chat-3",
        job_type=JobType.CHAT,
        status=JobStatus.QUEUED,
        started_at=chat_dead,
        heartbeat_at=chat_dead,
    )
    _add_job(
        ctx,
        job_id="lora-3",
        job_type=JobType.LORA_TRAINING,
        status=JobStatus.RUNNING,
        started_at=lora_dead,
        heartbeat_at=lora_dead,
    )
    with ctx.db() as session:
        session.add(User(id="u1", username="u1", password_hash="x"))
        session.add(
            UserLora(
                id="L-tick",
                user_id="u1",
                name="L-tick",
                slug="L-tick",
                status=LoraStatus.TRAINING,
                training_job_id="lora-3",
            ),
        )
        session.commit()

    recovered_jobs, reconciled_loras = _run_stale_job_reaper_tick(ctx, now=_NOW)

    assert recovered_jobs == 2
    assert reconciled_loras == 1
    assert _job_status(ctx, "chat-3") == JobStatus.FAILED
    assert _job_status(ctx, "lora-3") == JobStatus.FAILED
    with ctx.db() as s:
        assert get_user_lora(s, "L-tick", include_deleted_rows=True).status == LoraStatus.FAILED
