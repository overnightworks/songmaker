"""Tests for the background-loop health registry."""

from __future__ import annotations

import asyncio
import itertools
import os
import threading
from collections.abc import Iterator
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fakeredis
import pytest
from support.loop_ticks import ScriptedTickLock, run_ticks_observing_status
from support.object_store import an_object_store
from support.owner_lease_epoch import aged_epoch
from support.web_app import (
    TEST_SECRET,
    arrange_fake_async_redis,
    make_fake_redis,
    make_test_app,
)

import songmaker_cli.cover_runner as cover_runner
import songmaker_cli.lifecycle as lifecycle
import songmaker_cli.server as server
from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import BACKGROUND_LOOP_FAILURE_THRESHOLD
from songmaker_cli.db.models import (
    Album,
    AlbumCoverSuggestion,
    Generation,
    Job,
    Song,
    User,
    Version,
)
from songmaker_cli.health_types import BackgroundLoopRegistry, BackgroundLoopStatus
from songmaker_cli.job_timing import QUEUED_JOB_STALE_THRESHOLD_SECONDS
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.lifecycle import (
    SCORE_BACKFILL_LOCK_NAME,
    TICK_LOCK_LASTS,
    BackfillResult,
    BackgroundLoopName,
)


async def _failing_loop_tick(registry: BackgroundLoopRegistry) -> None:
    try:
        raise RuntimeError("redis unavailable")
    except RuntimeError as exc:
        registry.record_failure(BackgroundLoopName.SCORE_BACKFILL, exc)


def test_fake_loop_becomes_failing_after_the_named_failure_threshold() -> None:
    registry = BackgroundLoopRegistry()

    for _ in range(BACKGROUND_LOOP_FAILURE_THRESHOLD):
        asyncio.run(_failing_loop_tick(registry))

    health = registry.loop_health()[BackgroundLoopName.SCORE_BACKFILL]
    assert health.status is BackgroundLoopStatus.FAILING
    assert health.consecutive_failures == BACKGROUND_LOOP_FAILURE_THRESHOLD
    assert health.last_error == "RuntimeError"


def test_successful_fake_tick_resets_a_failing_loop() -> None:
    registry = BackgroundLoopRegistry()
    for _ in range(BACKGROUND_LOOP_FAILURE_THRESHOLD):
        asyncio.run(_failing_loop_tick(registry))

    registry.record_success(BackgroundLoopName.SCORE_BACKFILL)

    health = registry.loop_health()[BackgroundLoopName.SCORE_BACKFILL]
    assert health.status is BackgroundLoopStatus.OK
    assert health.consecutive_failures == 0
    assert health.last_error is None


def test_loop_error_detail_does_not_expose_its_message() -> None:
    # defect:#1590 — cleanup loop replaces TTL reconciliation.
    registry = BackgroundLoopRegistry()

    registry.record_failure(
        BackgroundLoopName.SCORE_BACKFILL,
        RuntimeError("api_key=top-secret\\ntraceback"),
    )

    health = registry.loop_health()[BackgroundLoopName.SCORE_BACKFILL]
    assert health.last_error == "RuntimeError"
    assert "api_key" not in health.last_error

    registry.mark_dead(
        BackgroundLoopName.SESSION_CLEANUP,
        asyncio.CancelledError("token=top-secret"),
    )

    health = registry.loop_health()[BackgroundLoopName.SESSION_CLEANUP]
    assert health.last_error == "CancelledError"
    assert "token" not in health.last_error


def test_loop_health_returns_copies_of_the_registry_state() -> None:
    registry = BackgroundLoopRegistry()

    snapshot = registry.loop_health()
    snapshot[BackgroundLoopName.SCORE_BACKFILL].is_alive = False

    health = registry.loop_health()[BackgroundLoopName.SCORE_BACKFILL]
    assert health.is_alive is True


def test_score_backfill_generation_failure_marks_the_tick_failed(monkeypatch) -> None:
    registry = BackgroundLoopRegistry()
    free_lock = ScriptedTickLock(SCORE_BACKFILL_LOCK_NAME, ["generation"])
    app = SimpleNamespace(
        state=SimpleNamespace(
            background_loop_registry=registry,
            ctx=SimpleNamespace(db=lambda: nullcontext(), async_redis=free_lock.async_redis),
        ),
    )
    tick_started = False

    async def fake_sleep(_seconds: float) -> None:
        nonlocal tick_started
        if tick_started:
            raise asyncio.CancelledError()
        tick_started = True

    failing_auto_score = AsyncMock(side_effect=RuntimeError("token=top-secret"))

    monkeypatch.setattr(lifecycle.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(lifecycle, "_clear_resolved_backfill_attempts", AsyncMock())
    monkeypatch.setattr(lifecycle, "_pick_unscored_generations", lambda *_args: [("g1", "s1")])
    monkeypatch.setattr(lifecycle, "_exhausted_backfill_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr(lifecycle, "_record_backfill_attempt", AsyncMock())
    monkeypatch.setattr("songmaker_cli.arq_pool.get_arq_pool", lambda: object())
    monkeypatch.setattr("songmaker_cli.jobs._auto_score_generation", failing_auto_score)

    loop = lifecycle.score_backfill_loop(app)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loop)

    health = registry.loop_health()[BackgroundLoopName.SCORE_BACKFILL]
    failing_auto_score.assert_awaited_once()
    assert health.consecutive_failures == 1
    assert health.last_error == "RuntimeError"


def _run_score_backfill_ticks(
    monkeypatch, *, lock_results: list, backfill: AsyncMock, failures_before: int = 0,
) -> list[BackgroundLoopStatus]:
    """Run one score-backfill tick per lock result; return the status seen before each tick
    and after the last one."""
    registry = BackgroundLoopRegistry()
    for _ in range(failures_before):
        registry.record_failure(BackgroundLoopName.SCORE_BACKFILL, RuntimeError("earlier"))
    tick_lock = ScriptedTickLock(SCORE_BACKFILL_LOCK_NAME, lock_results)
    app = SimpleNamespace(
        state=SimpleNamespace(
            background_loop_registry=registry,
            ctx=SimpleNamespace(async_redis=tick_lock.async_redis),
        ),
    )
    monkeypatch.setattr(lifecycle, "backfill_unscored_generations", backfill)
    monkeypatch.setattr("songmaker_cli.arq_pool.get_arq_pool", lambda: object())
    return run_ticks_observing_status(
        monkeypatch, lifecycle.score_backfill_loop(app), registry,
        BackgroundLoopName.SCORE_BACKFILL, len(lock_results), before_tick=tick_lock.before_tick,
    )


def test_score_backfill_skips_the_tick_and_reads_ok_while_another_process_holds_the_lock(
    monkeypatch,
) -> None:
    backfill = AsyncMock()

    statuses = _run_score_backfill_ticks(
        monkeypatch, lock_results=[None], backfill=backfill,
        failures_before=BACKGROUND_LOOP_FAILURE_THRESHOLD,
    )

    backfill.assert_not_awaited()
    assert statuses == [BackgroundLoopStatus.FAILING, BackgroundLoopStatus.OK]


def test_score_backfill_reads_failing_during_a_redis_outage_and_runs_the_next_tick(
    monkeypatch,
) -> None:
    backfill = AsyncMock(return_value=BackfillResult(dispatched=0, first_error=None))
    outage = [RuntimeError("redis unavailable")] * BACKGROUND_LOOP_FAILURE_THRESHOLD

    statuses = _run_score_backfill_ticks(
        monkeypatch, lock_results=[*outage, "generation"], backfill=backfill,
    )

    assert statuses[BACKGROUND_LOOP_FAILURE_THRESHOLD] is BackgroundLoopStatus.FAILING
    backfill.assert_awaited_once()


@pytest.mark.parametrize("dispatched", [0, 2])
def test_a_healthy_score_backfill_tick_resets_a_failing_loop(monkeypatch, dispatched) -> None:
    failing_tick = BackfillResult(dispatched=0, first_error=RuntimeError("scorer unavailable"))
    backfill = AsyncMock(
        side_effect=[
            *[failing_tick] * BACKGROUND_LOOP_FAILURE_THRESHOLD,
            BackfillResult(dispatched=dispatched, first_error=None),
        ],
    )

    statuses = _run_score_backfill_ticks(
        monkeypatch, lock_results=["generation"] * (BACKGROUND_LOOP_FAILURE_THRESHOLD + 1),
        backfill=backfill,
    )

    assert statuses[BACKGROUND_LOOP_FAILURE_THRESHOLD] is BackgroundLoopStatus.FAILING
    assert statuses[-1] is BackgroundLoopStatus.OK


def _add_a_stale_job(factory, number: int) -> None:
    """A chat job the reaper fails by age, as no worker signal covers it."""
    long_ago = datetime.now(timezone.utc) - timedelta(
        seconds=QUEUED_JOB_STALE_THRESHOLD_SECONDS + 60,
    )
    with factory() as session:
        session.add(Job(
            id=f"stale-{number}", type=JobType.CHAT, status=JobStatus.QUEUED,
            started_at=long_ago, heartbeat_at=long_ago,
        ))
        session.commit()


def _stale_job_was_reaped(factory, number: int) -> bool:
    with factory() as session:
        return session.get(Job, f"stale-{number}").status == JobStatus.FAILED


def _add_an_unscored_generation(factory, number: int) -> None:
    with factory() as session:
        if session.get(User, "u1") is None:
            session.add(User(id="u1", username="user1", role="user"))
            session.flush()
            session.add(Album(id="a1", title="Album", artist="Artist", created_by="u1"))
        session.add(Song(
            id=f"s{number}", title="Song", album_id="a1", slug=f"song-{number}",
            track_number=number,
        ))
        session.flush()
        session.add(Version(
            id=f"v{number}", song_id=f"s{number}", version_number=1, lyrics="", prompt="",
            bpm=120, audio_duration=60, key_scale="Am",
        ))
        session.flush()
        session.add(Generation(
            id=f"g{number}", song_id=f"s{number}", version_id=f"v{number}",
            generation_number=1, mp3_path=f"g{number}.mp3",
        ))
        session.commit()


def _generation_was_handed_to_scoring(factory, number: int) -> bool:
    with factory() as session:
        return session.query(Job).filter_by(type=JobType.SCORE, song_id=f"s{number}").count() == 1


class _TickingProcess:
    """One web process's periodic loop over a database and a Redis server others share.

    Each ``run_one_tick`` adds one piece of work the loop does, runs one tick and returns
    whether that piece was done: a stale job reaped, an unscored generation handed to scoring.
    """

    _WORK = {
        BackgroundLoopName.STALE_JOB_REAPER: (_add_a_stale_job, _stale_job_was_reaped),
        BackgroundLoopName.SCORE_BACKFILL: (
            _add_an_unscored_generation, _generation_was_handed_to_scoring,
        ),
    }
    _LOOPS = {
        BackgroundLoopName.STALE_JOB_REAPER: lifecycle.stale_job_reaper_loop,
        BackgroundLoopName.SCORE_BACKFILL: lifecycle.score_backfill_loop,
    }

    def __init__(
        self, monkeypatch, server: fakeredis.FakeServer, factory, tmp_path,
        loop_name: BackgroundLoopName, work_numbers: Iterator[int],
    ):
        self.registry = BackgroundLoopRegistry()
        self.loop_name = loop_name
        self._monkeypatch = monkeypatch
        self._factory = factory
        self._work_numbers = work_numbers
        self._ctx = AppContext(
            object_store=an_object_store(),
            db=factory, audio_dir=tmp_path / "audio", data_dir=tmp_path / "data",
            signing_key=TEST_SECRET, redis=make_fake_redis(),
            async_redis=fakeredis.FakeAsyncRedis(server=server),
        )
        self._app = SimpleNamespace(
            state=SimpleNamespace(background_loop_registry=self.registry, ctx=self._ctx),
        )

    def run_one_tick(self) -> bool:
        add_work, work_was_done = self._WORK[self.loop_name]
        number = next(self._work_numbers)
        add_work(self._factory, number)
        self._monkeypatch.setattr(
            "songmaker_cli.arq_pool.get_arq_pool",
            lambda: fakeredis.FakeAsyncRedis(decode_responses=True),
        )
        run_ticks_observing_status(
            self._monkeypatch, self._LOOPS[self.loop_name](self._app), self.registry,
            self.loop_name, 1,
        )
        arrange_fake_async_redis(self._ctx.async_redis, _nothing)
        return work_was_done(self._factory, number)


@pytest.fixture
def ticking_processes(monkeypatch, pg_factory, tmp_path):
    """Builds web processes of one loop that share the database and a Redis server."""
    work_numbers = itertools.count(1)

    def build(server: fakeredis.FakeServer, loop_name: BackgroundLoopName) -> _TickingProcess:
        return _TickingProcess(
            monkeypatch, server, pg_factory, tmp_path, loop_name, work_numbers,
        )

    return build


async def _nothing(_redis) -> None:
    return None


def _settle_the_fake_servers_epoch(server: fakeredis.FakeServer) -> None:
    arrange_fake_async_redis(
        fakeredis.FakeAsyncRedis(server=server),
        lambda redis: redis.set(*aged_epoch(TICK_LOCK_LASTS.total_seconds())),
    )


TICKING_LOOPS = [BackgroundLoopName.STALE_JOB_REAPER, BackgroundLoopName.SCORE_BACKFILL]


@pytest.mark.parametrize("loop_name", TICKING_LOOPS)
def test_one_of_two_processes_runs_a_tick_and_the_other_reads_ok(
    ticking_processes, loop_name: BackgroundLoopName,
) -> None:
    server = fakeredis.FakeServer()
    _settle_the_fake_servers_epoch(server)
    first = ticking_processes(server, loop_name)
    second = ticking_processes(server, loop_name)

    ran = [first.run_one_tick(), second.run_one_tick()]

    assert ran == [True, False]
    assert second.registry.loop_health()[loop_name].status is BackgroundLoopStatus.OK


@pytest.mark.parametrize("loop_name", TICKING_LOOPS)
def test_a_tick_waits_out_a_redis_restart_without_a_failure_and_runs_once_it_settled(
    ticking_processes, loop_name: BackgroundLoopName,
) -> None:
    server = fakeredis.FakeServer()
    _settle_the_fake_servers_epoch(server)
    process = ticking_processes(server, loop_name)
    arrange_fake_async_redis(
        fakeredis.FakeAsyncRedis(server=server), lambda redis: redis.flushall(),
    )

    ran_just_after_the_restart = process.run_one_tick()
    _settle_the_fake_servers_epoch(server)
    ran_once_settled = process.run_one_tick()

    assert (ran_just_after_the_restart, ran_once_settled) == (False, True)
    assert process.registry.loop_health()[loop_name].status is BackgroundLoopStatus.OK


def test_finished_lifecycle_loop_is_dead_outside_shutdown(
    tmp_path, monkeypatch, mock_arq_pool, caplog,
    monitoring_headers, pg_factory,
) -> None:
    # defect:#1590 — cleanup loop replaces TTL reconciliation.
    async def stopped_loop(_app) -> None:
        return None

    monkeypatch.setattr(server, "session_cleanup_loop", stopped_loop)
    client, _ = make_test_app(tmp_path, factory=pg_factory)
    with client:
        response = client.get("/health/details", headers=monitoring_headers)

    health = response.json()["background_loops"][BackgroundLoopName.SESSION_CLEANUP]
    assert health["state"] == BackgroundLoopStatus.DEAD
    assert health["last_error"] == "task ended"
    assert "Background loop session_cleanup ended" in caplog.text


def test_failed_lifecycle_loop_logs_its_exception(
    tmp_path, monkeypatch, mock_arq_pool, caplog,
    monitoring_headers, pg_factory,
) -> None:
    # defect:#1590 — cleanup loop replaces TTL reconciliation.
    async def failed_loop(_app) -> None:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(server, "session_cleanup_loop", failed_loop)
    client, _ = make_test_app(tmp_path, factory=pg_factory)
    with client:
        response = client.get("/health/details", headers=monitoring_headers)

    assert response.status_code == 200
    matching_records = [
        record for record in caplog.records
        if record.getMessage() == "Background loop session_cleanup ended"
    ]
    assert len(matching_records) == 1
    assert isinstance(matching_records[0].exc_info[1], RuntimeError)


def test_externally_cancelling_one_lifecycle_loop_marks_only_that_loop_dead(
    tmp_path, monkeypatch, mock_arq_pool,
    monitoring_headers, pg_factory,
) -> None:
    # defect:#1590 — cleanup loop replaces TTL reconciliation.
    import songmaker_cli.arq_pool as arq_pool

    monkeypatch.setattr(arq_pool, "is_music_worker_healthy", AsyncMock(return_value=True))
    monkeypatch.setattr(arq_pool, "is_scoring_worker_healthy", AsyncMock(return_value=True))
    client, _ = make_test_app(tmp_path, factory=pg_factory)
    with client:
        before_cancellation = client.get("/health/details", headers=monitoring_headers)
        assert before_cancellation.status_code == 200
        assert before_cancellation.json()["status"] == "ok"

        tasks = client.app.state.background_loop_tasks
        task = tasks[BackgroundLoopName.SESSION_CLEANUP]

        async def cancel_and_wait_for_loop() -> None:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        client.portal.call(cancel_and_wait_for_loop)
        after_cancellation = client.get("/health/details", headers=monitoring_headers)

    assert after_cancellation.status_code == 200
    assert after_cancellation.json()["status"] == "ok"
    loop_health = after_cancellation.json()["background_loops"]
    assert loop_health[BackgroundLoopName.SESSION_CLEANUP]["state"] == BackgroundLoopStatus.DEAD
    assert {
        name: health["state"]
        for name, health in loop_health.items()
        if name != BackgroundLoopName.SESSION_CLEANUP
    } == {
        BackgroundLoopName.RESOURCE_EVENT_CLEANUP: BackgroundLoopStatus.OK,
        BackgroundLoopName.SCORE_BACKFILL: BackgroundLoopStatus.OK,
        BackgroundLoopName.STALE_JOB_REAPER: BackgroundLoopStatus.OK,
        BackgroundLoopName.OWNER_LEASE: BackgroundLoopStatus.OK,
        BackgroundLoopName.OWNER_LAPSES: BackgroundLoopStatus.OK,
        BackgroundLoopName.OWNER_GONE_REAPER: BackgroundLoopStatus.OK,
        BackgroundLoopName.COVER_RUNNER: BackgroundLoopStatus.OK,
    }


def test_lifecycle_shutdown_does_not_mark_cancelled_loops_dead(
    tmp_path, mock_arq_pool, pg_factory,
) -> None:
    client, _ = make_test_app(tmp_path, factory=pg_factory)
    with client:
        registry = client.app.state.background_loop_registry

    assert all(
        health.status is BackgroundLoopStatus.OK
        for health in registry.loop_health().values()
    )


def test_web_cover_runner_is_visible_in_lifecycle_health(
    tmp_path, monkeypatch, mock_arq_pool,
    monitoring_headers, pg_factory,
) -> None:
    started = threading.Event()

    async def idle_cover_runner(app, registry) -> None:
        registry.record_success(BackgroundLoopName.COVER_RUNNER)
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(server, "cover_runner_loop", idle_cover_runner)
    client, _ = make_test_app(tmp_path, factory=pg_factory)

    with client:
        assert started.wait(timeout=1)
        health = client.get(
            "/health/details", headers=monitoring_headers,
        ).json()["background_loops"]
        assert health[BackgroundLoopName.COVER_RUNNER]["state"] == BackgroundLoopStatus.OK


def test_a_web_start_removes_the_suggestion_file_and_staging_directory_a_failed_cover_left(
    tmp_path, mock_arq_pool, pg_factory,
) -> None:
    audio_dir = tmp_path / "audio"
    png = audio_dir / "cover-suggestions" / "album" / "interrupted.png"
    staging_dir = cover_runner.cover_staging_path(audio_dir, "cover-job")

    def seed_interrupted_cover(session) -> None:
        png.parent.mkdir(parents=True)
        png.write_bytes(b"png")
        staging_dir.mkdir()
        session.add(User(id="u1", username="u1"))
        session.flush()
        session.add(Album(id="album", title="Album", artist="Artist", created_by="u1"))
        session.flush()
        session.add(Job(
            id="cover-job", type=JobType.COVER, status=JobStatus.FAILED, album_id="album",
        ))
        session.flush()
        session.add(AlbumCoverSuggestion(
            id="interrupted", album_id="album", job_id="cover-job",
            png_path="cover-suggestions/album/interrupted.png",
        ))

    client, factory = make_test_app(tmp_path, seed_db=seed_interrupted_cover, factory=pg_factory)
    with client:
        pass

    with factory() as session:
        assert session.get(Job, "cover-job").status == JobStatus.FAILED
        assert session.query(AlbumCoverSuggestion).count() == 0
    assert not png.exists()
    assert not staging_dir.exists()


def test_booting_the_web_reports_every_loop_ok_and_starts_no_agent_cli(
    tmp_path, monkeypatch, mock_arq_pool, monitoring_headers, pg_factory,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    spawn_log = tmp_path / "spawns.log"
    for binary in ("claude", "grok", "codex"):
        stub = bin_dir / binary
        stub.write_text(f"#!/bin/sh\necho {binary} >> {spawn_log}\n")
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    client, _ = make_test_app(tmp_path, factory=pg_factory)

    with client:
        health = client.get(
            "/health/details", headers=monitoring_headers,
        ).json()["background_loops"]

    assert {name: loop["state"] for name, loop in health.items()} == {
        name.value: BackgroundLoopStatus.OK for name in BackgroundLoopName
    }
    assert not spawn_log.exists()
