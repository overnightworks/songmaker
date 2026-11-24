"""Tests for the lifecycle-owned stale-job reaper and LoRA reconciliation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from support.loop_ticks import ScriptedTickLock, run_ticks_observing_status
from support.object_store import an_object_store
from support.web_app import TEST_SECRET, make_fake_async_redis, make_fake_redis
from tandem import Roster

import songmaker_cli.cover_runner as cover_runner
from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import BACKGROUND_LOOP_FAILURE_THRESHOLD, LoraStatus
from songmaker_cli.db.models import Album, AlbumCoverSuggestion, Job, User, UserLora
from songmaker_cli.db.queries.loras import get_user_lora
from songmaker_cli.health_types import BackgroundLoopRegistry, BackgroundLoopStatus
from songmaker_cli.job_timing import (
    JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS,
    QUEUED_JOB_STALE_THRESHOLD_SECONDS,
    STALE_JOB_THRESHOLDS,
    WORKER_RESTART_GRACE_SECONDS,
)
from songmaker_cli.job_types import JobStatus, JobType, WorkerLivenessSignal
from songmaker_cli.lifecycle import (
    JOB_REAPER_LOCK_NAME,
    BackgroundLoopName,
    _run_stale_job_reaper_tick,
    reap_stale_jobs,
    stale_job_reaper_loop,
)
from songmaker_cli.messages import Message, message
from songmaker_cli.settings import get_settings
from songmaker_cli.timestamps import utcnow
from songmaker_cli.worker_liveness import (
    ACESTEP_LAST_ALIVE_KEY,
    WORKER_KINDS,
    WorkerLiveness,
    acestep_worker_liveness,
    every_worker_kind_leases,
    worker_kind_liveness,
    worker_liveness_by_job_type,
)


@pytest.fixture
def ctx(tmp_path: Path, pg_factory) -> AppContext:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    return AppContext(
        object_store=an_object_store(),
        db=pg_factory, audio_dir=audio_dir, data_dir=tmp_path / "data",
        signing_key=TEST_SECRET, redis=make_fake_redis(), async_redis=make_fake_async_redis(),
    )


def _dead_process_time(now: datetime, threshold_seconds: int) -> datetime:
    """A timestamp old enough that its owning process looks dead."""
    return now - timedelta(seconds=threshold_seconds + 60)


def _add_job(
    ctx: AppContext, *, job_id: str, job_type: str, status: str,
    started_at: datetime | None = None, heartbeat_at: datetime | None = None,
    queue_reason_message: Message | None = None,
) -> None:
    with ctx.db() as session:
        kwargs = {}
        if started_at is not None:
            kwargs["started_at"] = started_at
        if heartbeat_at is not None:
            kwargs["heartbeat_at"] = heartbeat_at
        session.add(
            Job(
                id=job_id, type=job_type, status=status,
                queue_reason_message=queue_reason_message, **kwargs,
            )
        )
        session.commit()


def _job_status(ctx: AppContext, job_id: str) -> str:
    with ctx.db() as session:
        return session.query(Job).filter_by(id=job_id).first().status


class TestLifecycleReaper:
    def test_web_cover_queue_uses_its_age_guard_not_music_worker_liveness(self, ctx) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        _add_job(
            ctx, job_id="web-cover", job_type=JobType.COVER, status=JobStatus.QUEUED,
            started_at=now - timedelta(seconds=QUEUED_JOB_STALE_THRESHOLD_SECONDS + 1),
            heartbeat_at=now,
        )

        recovered = reap_stale_jobs(
            ctx,
            now=now,
            worker_liveness={JobType.COVER: WorkerLiveness.DEAD},
        )

        assert recovered == 1
        with ctx.db() as session:
            job = session.query(Job).filter_by(id="web-cover").one()
            assert job.error_type == "queued_too_long"

    def test_fails_an_old_queued_chat_job_when_no_worker_signal_exists(self, ctx) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        dead = _dead_process_time(now, QUEUED_JOB_STALE_THRESHOLD_SECONDS)
        _add_job(
            ctx, job_id="chat-1", job_type=JobType.CHAT, status=JobStatus.QUEUED,
            started_at=dead,
            heartbeat_at=dead,
            queue_reason_message=message("jobWait.voiceTraining"),
        )

        recovered = reap_stale_jobs(ctx, now=now)

        assert recovered == 1
        with ctx.db() as session:
            job = session.query(Job).filter_by(id="chat-1").one()
            assert job.status == JobStatus.FAILED
            assert job.error_message == message("jobFailure.queuedTooLong")
            assert job.error_type == "queued_too_long"
            assert job.queue_reason_message is None

    def test_fails_an_old_queued_job_whose_wait_names_an_unknown_key(self, ctx) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        dead = _dead_process_time(now, QUEUED_JOB_STALE_THRESHOLD_SECONDS)
        with ctx.db() as session:
            session.execute(sa.text(
                "INSERT INTO jobs (id, type, status, progress, heartbeat_at, started_at, "
                "queue_reason_message) VALUES ('retired-wait', 'chat', 'queued', 0, :dead, "
                ":dead, CAST('{\"key\": \"jobWait.retired\", \"values\": {}}' AS json))"
            ), {"dead": dead})
            session.commit()

        recovered = reap_stale_jobs(ctx, now=now)

        assert recovered == 1
        with ctx.db() as session:
            job = session.query(Job).filter_by(id="retired-wait").one()
            assert job.status == JobStatus.FAILED
            assert job.queue_reason_message is None

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
            assert job.error_message == message("jobFailure.tookTooLong")
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
            assert job.error_message == message("jobFailure.noWorkerAlive")

    @pytest.mark.parametrize(
        ("seconds_since_alive", "expected_status"),
        [
            pytest.param(5, JobStatus.QUEUED, id="inside the restart grace"),
            pytest.param(WORKER_RESTART_GRACE_SECONDS + 60, JobStatus.FAILED, id="past it"),
        ],
    )
    def test_a_queued_score_job_follows_the_scoring_roster(
        self, ctx, monkeypatch, seconds_since_alive: int, expected_status: str,
    ) -> None:
        now = utcnow()
        monkeypatch.setattr(
            "songmaker_cli.worker_liveness._PROCESS_STARTED_AT",
            now - timedelta(seconds=2 * WORKER_RESTART_GRACE_SECONDS),
        )
        ctx.redis.set(
            WORKER_KINDS[WorkerLivenessSignal.SCORING].last_alive_key,
            (now - timedelta(seconds=seconds_since_alive)).isoformat(),
        )
        _add_job(
            ctx, job_id="queued-score", job_type=JobType.SCORE,
            status=JobStatus.QUEUED, started_at=now, heartbeat_at=now,
        )

        reap_stale_jobs(
            ctx, now=now,
            rosters={WorkerLivenessSignal.SCORING: Roster(holders=frozenset(), settled=True)},
        )

        assert _job_status(ctx, "queued-score") == expected_status

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
            assert job.error_message == message("jobFailure.queuedTooLong")
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
            ctx, job_id=f"{job_type}-alive", job_type=job_type,
            status=JobStatus.QUEUED,
            started_at=now - timedelta(seconds=thresholds.queued_seconds + 1), heartbeat_at=now,
        )

        recovered = reap_stale_jobs(
            ctx,
            now=now,
            worker_liveness={job_type: WorkerLiveness.ALIVE},
        )

        assert recovered == 0
        assert _job_status(ctx, f"{job_type}-alive") == JobStatus.QUEUED

        with ctx.db() as session:
            job = session.query(Job).filter_by(id=f"{job_type}-alive").one()
            job.started_at = now - timedelta(seconds=full_queue_bound + 1)
            session.commit()

        assert reap_stale_jobs(
            ctx, now=now, worker_liveness={job_type: WorkerLiveness.ALIVE},
        ) == 1
        with ctx.db() as session:
            job = session.query(Job).filter_by(id=f"{job_type}-alive").one()
            assert job.error_message == message("jobFailure.queuedFullQueueBound")
            assert job.error_type == "queued_full_queue_bound"

    def test_restart_window_keeps_a_1101_second_queued_job_until_the_full_queue_bound(
        self, ctx,
    ) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        _add_job(
            ctx, job_id="restart-window-generate", job_type=JobType.GENERATE,
            status=JobStatus.QUEUED,
            started_at=now - timedelta(seconds=1101), heartbeat_at=now,
        )
        ctx.redis.set(ACESTEP_LAST_ALIVE_KEY, now.isoformat())
        ctx.redis.set(WORKER_KINDS[WorkerLivenessSignal.MUSIC].last_alive_key, now.isoformat())

        liveness = worker_liveness_by_job_type(
            acestep=acestep_worker_liveness(ctx.redis, ["ace-1"], now=now),
            music=worker_kind_liveness(
                ctx.redis, WorkerLivenessSignal.MUSIC,
                Roster(holders=frozenset(), settled=True), now=now,
            ),
            scoring=WorkerLiveness.UNKNOWN,
        )

        assert reap_stale_jobs(ctx, now=now, worker_liveness=liveness) == 0
        assert _job_status(ctx, "restart-window-generate") == JobStatus.QUEUED

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
    tick_lock = ScriptedTickLock(
        JOB_REAPER_LOCK_NAME, ["generation"] * BACKGROUND_LOOP_FAILURE_THRESHOLD,
    )
    app = SimpleNamespace(
        state=SimpleNamespace(
            ctx=SimpleNamespace(
                db=ctx.db,
                async_redis=tick_lock.async_redis,
                kind_leases=every_worker_kind_leases(tick_lock.async_redis),
                redis=SimpleNamespace(
                    exists=lambda *_args, **_kwargs: False,
                    get=lambda *_args, **_kwargs: None,
                ),
            ),
            background_loop_registry=registry,
        ),
    )
    _add_job(ctx, job_id="missing-policy", job_type="unknown_type", status=JobStatus.QUEUED)

    run_ticks_observing_status(
        monkeypatch, stale_job_reaper_loop(app), registry,
        BackgroundLoopName.STALE_JOB_REAPER, BACKGROUND_LOOP_FAILURE_THRESHOLD,
        before_tick=tick_lock.before_tick,
    )

    health = registry.loop_health()[BackgroundLoopName.STALE_JOB_REAPER]
    assert health.status is BackgroundLoopStatus.FAILING
    assert health.consecutive_failures == BACKGROUND_LOOP_FAILURE_THRESHOLD
    assert health.last_error == "RuntimeError"


def _run_reaper_ticks(
    monkeypatch, *, lock_results: list, tick: MagicMock, failures_before: int = 0,
) -> list[BackgroundLoopStatus]:
    """Run one reaper tick per lock result; return the status seen before each tick
    and after the last one."""
    registry = BackgroundLoopRegistry()
    for _ in range(failures_before):
        registry.record_failure(BackgroundLoopName.STALE_JOB_REAPER, RuntimeError("earlier"))
    tick_lock = ScriptedTickLock(JOB_REAPER_LOCK_NAME, lock_results)
    app = SimpleNamespace(
        state=SimpleNamespace(
            ctx=SimpleNamespace(
                async_redis=tick_lock.async_redis,
                kind_leases=every_worker_kind_leases(tick_lock.async_redis),
            ),
            background_loop_registry=registry,
        ),
    )
    monkeypatch.setattr("songmaker_cli.lifecycle._run_stale_job_reaper_tick", tick)
    return run_ticks_observing_status(
        monkeypatch, stale_job_reaper_loop(app), registry,
        BackgroundLoopName.STALE_JOB_REAPER, len(lock_results), before_tick=tick_lock.before_tick,
    )


def test_reaper_skips_the_tick_and_reads_ok_while_another_process_holds_the_lock(
    monkeypatch,
) -> None:
    tick = MagicMock(return_value=(0, 0))

    statuses = _run_reaper_ticks(
        monkeypatch, lock_results=[None], tick=tick,
        failures_before=BACKGROUND_LOOP_FAILURE_THRESHOLD,
    )

    tick.assert_not_called()
    assert statuses == [BackgroundLoopStatus.FAILING, BackgroundLoopStatus.OK]


def test_a_good_reaper_tick_resets_a_failing_loop(monkeypatch) -> None:
    tick = MagicMock(
        side_effect=[*[RuntimeError("database unavailable")] * BACKGROUND_LOOP_FAILURE_THRESHOLD,
                     (0, 0)],
    )

    statuses = _run_reaper_ticks(
        monkeypatch,
        lock_results=["generation"] * (BACKGROUND_LOOP_FAILURE_THRESHOLD + 1),
        tick=tick,
    )

    assert statuses[BACKGROUND_LOOP_FAILURE_THRESHOLD] is BackgroundLoopStatus.FAILING
    assert statuses[-1] is BackgroundLoopStatus.OK


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
        session.add(User(id="u1", username="u1"))
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


def test_reaper_tick_leaves_a_stalled_cover_without_suggestion_and_staging_directory(ctx) -> None:
    now = datetime.now(timezone.utc)
    stalled = _dead_process_time(now, STALE_JOB_THRESHOLDS[JobType.COVER].heartbeat_seconds)
    png = ctx.audio_dir / "cover-suggestions" / "album" / "stalled.png"
    png.parent.mkdir(parents=True)
    png.write_bytes(b"png")
    staging_dir = cover_runner.cover_staging_path(ctx.audio_dir, "cover-job")
    staging_dir.mkdir()
    with ctx.db() as session:
        session.add(User(id="u1", username="u1"))
        session.flush()
        session.add(Album(id="album", title="Album", artist="Artist", created_by="u1"))
        session.flush()
        session.add(Job(
            id="cover-job", type=JobType.COVER, status=JobStatus.RUNNING, album_id="album",
            started_at=stalled, heartbeat_at=stalled,
        ))
        session.flush()
        session.add(AlbumCoverSuggestion(
            id="stalled", album_id="album", job_id="cover-job",
            png_path="cover-suggestions/album/stalled.png",
        ))
        session.commit()

    _run_stale_job_reaper_tick(ctx, now=now)

    assert _job_status(ctx, "cover-job") == JobStatus.FAILED
    with ctx.db() as session:
        assert session.query(AlbumCoverSuggestion).count() == 0
    assert not png.exists()
    assert not staging_dir.exists()
