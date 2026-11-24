"""The loops that end the jobs of an owner that is gone."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from types import SimpleNamespace

import fakeredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from support.job_owner import an_owner, create_job_of_owner
from support.loop_ticks import run_ticks_observing_status
from support.web_app import arrange_fake_async_redis, make_fake_async_redis, settle_owner_leases

from songmaker_cli import lifecycle
from songmaker_cli.constants import BACKGROUND_LOOP_FAILURE_THRESHOLD
from songmaker_cli.cover_runner import cover_staging_path
from songmaker_cli.db.models import Job
from songmaker_cli.db.queries.jobs import (
    JOB_ERROR_SERVER_RESTARTED,
    JobStatusUpdate,
    update_job_status,
)
from songmaker_cli.health_types import (
    BackgroundLoopName,
    BackgroundLoopRegistry,
    BackgroundLoopStatus,
)
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.lifecycle import (
    fail_jobs_of_dead_owners,
    owner_gone_reaper_loop,
    owner_lapse_loop,
    reconcile_ended_covers,
)
from songmaker_cli.worker_liveness import (
    WORKER_KINDS,
    JobOwner,
    every_worker_kind_leases,
    keep_kind_lease,
    owner_leases,
    worker_kind_leases,
)

OWNER = "this-process"
ANOTHER = "another-process"
DEADLINE_SECONDS = 10


class _UnreachableRedis(fakeredis.FakeAsyncRedis):
    async def execute_command(self, *args, **options):
        raise RedisConnectionError("down")


def _loop_app(async_redis, db, audio_dir: Path, leases=None) -> SimpleNamespace:
    """An app over ``async_redis``, its owner leases being ``leases`` when given."""
    return SimpleNamespace(state=SimpleNamespace(
        ctx=SimpleNamespace(
            owner_leases=leases or owner_leases(async_redis),
            kind_leases=every_worker_kind_leases(async_redis),
            owner_id=OWNER, db=db, audio_dir=audio_dir,
        ),
        background_loop_registry=BackgroundLoopRegistry(tuple(BackgroundLoopName)),
    ))


def _running_job_of(factory, owner: JobOwner | str) -> str:
    """A running chat job; an owner given as a bare id is one a job names without a generation."""
    with factory() as session:
        job = create_job_of_owner(session, JobType.CHAT, owner)
        assert update_job_status(session, job.id, JobStatusUpdate(JobStatus.RUNNING))
        session.commit()
        return job.id


def _status_and_error(factory, job_id: str) -> tuple[str, str | None]:
    with factory() as session:
        job = session.get(Job, job_id)
        return job.status, job.error_type


def test_the_owner_pass_keeps_ticking_and_shows_failing_while_redis_is_down(
    monkeypatch, pg_factory, tmp_path,
) -> None:
    _running_job_of(pg_factory, an_owner(ANOTHER))
    app = _loop_app(_UnreachableRedis(), pg_factory, tmp_path)

    statuses = run_ticks_observing_status(
        monkeypatch, owner_gone_reaper_loop(app), app.state.background_loop_registry,
        BackgroundLoopName.OWNER_GONE_REAPER, BACKGROUND_LOOP_FAILURE_THRESHOLD,
    )

    assert statuses[-1] is BackgroundLoopStatus.FAILING


def _own_lease_status_after_the_ticks(monkeypatch, server, pg_factory, tmp_path):
    app = _loop_app(server, pg_factory, tmp_path)
    return run_ticks_observing_status(
        monkeypatch, owner_gone_reaper_loop(app), app.state.background_loop_registry,
        BackgroundLoopName.OWNER_LEASE, BACKGROUND_LOOP_FAILURE_THRESHOLD,
    )[-1]


def test_the_owner_lease_shows_ok_while_this_process_holds_its_lease(
    monkeypatch, pg_factory, tmp_path,
) -> None:
    server = make_fake_async_redis()
    arrange_fake_async_redis(server, lambda fake: owner_leases(fake).renew(OWNER))

    status = _own_lease_status_after_the_ticks(monkeypatch, server, pg_factory, tmp_path)

    assert status is BackgroundLoopStatus.OK


def test_the_owner_lease_shows_failing_while_this_process_holds_none(
    monkeypatch, pg_factory, tmp_path,
) -> None:
    server = make_fake_async_redis()
    arrange_fake_async_redis(server, settle_owner_leases)

    status = _own_lease_status_after_the_ticks(monkeypatch, server, pg_factory, tmp_path)

    assert status is BackgroundLoopStatus.FAILING


def test_the_owner_lease_shows_failing_while_redis_is_down(
    monkeypatch, pg_factory, tmp_path,
) -> None:
    status = _own_lease_status_after_the_ticks(
        monkeypatch, _UnreachableRedis(), pg_factory, tmp_path,
    )

    assert status is BackgroundLoopStatus.FAILING


@pytest.mark.parametrize("job_names_its_generation", [True, False])
def test_the_lapse_loop_ends_the_jobs_of_an_owner_whose_lease_ended(
    job_names_its_generation, pg_factory, tmp_path,
) -> None:
    server = make_fake_async_redis()
    app = _loop_app(server, pg_factory, tmp_path)

    async def end_the_lease_of_another_and_wait_for_its_job() -> tuple[str, str | None]:
        await settle_owner_leases(server)
        leases = owner_leases(server)
        generation = (await leases.renew(ANOTHER)).generation
        job_id = _running_job_of(
            pg_factory, an_owner(ANOTHER, generation) if job_names_its_generation else ANOTHER,
        )
        await leases.end(ANOTHER, generation)
        loop_task = asyncio.ensure_future(owner_lapse_loop(app))
        try:
            async with asyncio.timeout(DEADLINE_SECONDS):
                while _status_and_error(pg_factory, job_id)[0] == JobStatus.RUNNING:
                    await asyncio.sleep(0.01)
        finally:
            loop_task.cancel()
            await asyncio.gather(loop_task, return_exceptions=True)
        return _status_and_error(pg_factory, job_id)

    assert asyncio.run(end_the_lease_of_another_and_wait_for_its_job()) == (
        JobStatus.FAILED, JOB_ERROR_SERVER_RESTARTED.error_type,
    )


@pytest.mark.parametrize("kind", WORKER_KINDS, ids=lambda kind: kind.value)
def test_the_lapse_loop_leaves_no_trace_of_a_worker_whose_lease_ended(
    pg_factory, tmp_path, kind,
) -> None:
    server = make_fake_async_redis()
    app = _loop_app(server, pg_factory, tmp_path)

    async def family_keys() -> list[str]:
        return await server.keys(f"*:l:{WORKER_KINDS[kind].lease_family}:*")

    async def end_a_workers_lease_and_wait_for_the_loop() -> tuple[list[str], list[str]]:
        await settle_owner_leases(server)
        async with keep_kind_lease(worker_kind_leases(server, kind), ANOTHER):
            pass
        left_by_its_end = await family_keys()
        loop_task = asyncio.ensure_future(owner_lapse_loop(app))
        try:
            async with asyncio.timeout(DEADLINE_SECONDS):
                while await family_keys():
                    await asyncio.sleep(0.01)
        finally:
            loop_task.cancel()
            await asyncio.gather(loop_task, return_exceptions=True)
        return left_by_its_end, await family_keys()

    left_by_its_end, left_by_the_loop = asyncio.run(end_a_workers_lease_and_wait_for_the_loop())

    assert (bool(left_by_its_end), left_by_the_loop) == (True, [])


class _LeasesThatRunBeforeAnswering:
    """The owner leases, whose first ``state`` runs ``between`` after reading, before answering."""

    def __init__(self, leases, between) -> None:
        self._leases = leases
        self._between = between

    def __getattr__(self, name):
        return getattr(self._leases, name)

    async def state(self, holders):
        states = await self._leases.state(holders)
        between, self._between = self._between, None
        if between is not None:
            await between()
        return states


async def _fail_the_jobs_once(app: SimpleNamespace) -> None:
    await fail_jobs_of_dead_owners(app.state.ctx)


async def _run_one_pass(
    owner_pass, app: SimpleNamespace, monkeypatch, *, pauses_before: int,
) -> None:
    """Run ``owner_pass`` through its first pass and stop it at the pause after it.

    A loop that fails its pass records the failure and goes on, so the caller reads its health.
    """
    real_sleep = asyncio.sleep
    pauses_left = pauses_before

    async def sleep_until_the_pause_after_the_pass(seconds: float) -> None:
        nonlocal pauses_left
        if seconds != lifecycle.OWNER_GONE_CHECK_INTERVAL_SECONDS:
            await real_sleep(seconds)
        elif pauses_left:
            pauses_left -= 1
        else:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", sleep_until_the_pause_after_the_pass)
    with contextlib.suppress(asyncio.CancelledError):
        await owner_pass(app)


@pytest.mark.parametrize(
    ("owner_pass", "pauses_before", "loop_name"),
    [
        pytest.param(_fail_the_jobs_once, 0, None, id="the cleanup call"),
        pytest.param(owner_lapse_loop, 0, BackgroundLoopName.OWNER_LAPSES, id="the lapse loop"),
        pytest.param(
            owner_gone_reaper_loop, 1, BackgroundLoopName.OWNER_GONE_REAPER, id="the reaper loop",
        ),
    ],
)
def test_a_job_the_owner_wrote_after_its_lease_was_read_gone_keeps_running_while_the_old_ones_fail(
    owner_pass, pauses_before, loop_name, monkeypatch, pg_factory, tmp_path,
) -> None:
    server = make_fake_async_redis()

    async def run_the_pass_while_the_owner_starts_again() -> tuple:
        await settle_owner_leases(server)
        leases = owner_leases(server)
        lapsed = (await leases.renew(ANOTHER)).generation
        job_of_the_lapsed_generation = _running_job_of(pg_factory, an_owner(ANOTHER, lapsed))
        job_of_no_generation = _running_job_of(pg_factory, ANOTHER)
        await leases.end(ANOTHER, lapsed)
        new_jobs: list[str] = []
        new_generations: list[str] = []

        async def start_again_and_write_a_job() -> None:
            new_generations.append((await leases.renew(ANOTHER)).generation)
            new_jobs.append(_running_job_of(pg_factory, an_owner(ANOTHER, new_generations[0])))

        app = _loop_app(
            server, pg_factory, tmp_path,
            _LeasesThatRunBeforeAnswering(leases, start_again_and_write_a_job),
        )
        await _run_one_pass(owner_pass, app, monkeypatch, pauses_before=pauses_before)
        loop_health = app.state.background_loop_registry.loop_health()
        pass_failure = (
            (0, None) if loop_name is None
            else (loop_health[loop_name].consecutive_failures, loop_health[loop_name].last_error)
        )
        return (
            _status_and_error(pg_factory, job_of_the_lapsed_generation),
            _status_and_error(pg_factory, job_of_no_generation),
            _status_and_error(pg_factory, new_jobs[0]),
            new_generations[0] != lapsed,
            pass_failure,
        )

    failed = (JobStatus.FAILED, JOB_ERROR_SERVER_RESTARTED.error_type)
    assert asyncio.run(run_the_pass_while_the_owner_starts_again()) == (
        failed, failed, (JobStatus.RUNNING, None), True, (0, None),
    )


def test_a_job_of_a_generation_this_process_lost_fails_and_its_current_ones_keep_running(
    pg_factory, tmp_path,
) -> None:
    server = make_fake_async_redis()

    async def fail_the_jobs_of_this_process() -> tuple[tuple, tuple]:
        await settle_owner_leases(server)
        leases = owner_leases(server)
        lost = (await leases.renew(OWNER)).generation
        job_of_the_lost_generation = _running_job_of(pg_factory, an_owner(OWNER, lost))
        await leases.end(OWNER, lost)
        current = (await leases.renew(OWNER)).generation
        current_job = _running_job_of(pg_factory, an_owner(OWNER, current))
        ctx = SimpleNamespace(
            owner_leases=leases, owner_id=OWNER, db=pg_factory, audio_dir=tmp_path,
        )
        await fail_jobs_of_dead_owners(ctx)
        return (
            _status_and_error(pg_factory, job_of_the_lost_generation),
            _status_and_error(pg_factory, current_job),
        )

    assert asyncio.run(fail_the_jobs_of_this_process()) == (
        (JobStatus.FAILED, JOB_ERROR_SERVER_RESTARTED.error_type),
        (JobStatus.RUNNING, None),
    )


def test_a_cover_another_process_failed_while_this_lease_had_lapsed_leaves_no_staging(
    pg_factory, tmp_path,
) -> None:
    with pg_factory() as session:
        cover = create_job_of_owner(session, JobType.COVER, OWNER)
        for status in (JobStatus.RUNNING, JobStatus.FAILED):
            assert update_job_status(session, cover.id, JobStatusUpdate(status))
        session.commit()
        staging = cover_staging_path(tmp_path, cover.id)
    staging.mkdir(parents=True)
    ctx = SimpleNamespace(db=pg_factory, audio_dir=tmp_path)

    asyncio.run(reconcile_ended_covers(ctx))

    assert not staging.exists()
