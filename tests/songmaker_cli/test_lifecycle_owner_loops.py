"""The loops that end the jobs of an owner that is gone."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import fakeredis
from redis.exceptions import ConnectionError as RedisConnectionError
from support.loop_ticks import run_ticks_observing_status
from support.web_app import arrange_fake_async_redis, make_fake_async_redis, settle_owner_leases

from songmaker_cli.constants import BACKGROUND_LOOP_FAILURE_THRESHOLD, REDIS_KEY_PREFIX
from songmaker_cli.cover_runner import cover_staging_path
from songmaker_cli.db.models import Job
from songmaker_cli.db.queries.jobs import (
    JOB_ERROR_SERVER_RESTARTED,
    JobStatusUpdate,
    create_job,
    update_job_status,
)
from songmaker_cli.health_types import (
    BackgroundLoopName,
    BackgroundLoopRegistry,
    BackgroundLoopStatus,
)
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.lifecycle import (
    owner_gone_reaper_loop,
    owner_lapse_loop,
    reconcile_ended_covers,
)
from songmaker_cli.owner_lease_old_key import old_owner_key
from songmaker_cli.worker_liveness import owner_leases

OWNER = "this-process"
ANOTHER = "another-process"
DEADLINE_SECONDS = 10


class _UnreachableRedis(fakeredis.FakeAsyncRedis):
    async def execute_command(self, *args, **options):
        raise RedisConnectionError("down")


def _loop_app(async_redis, db, audio_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(
        ctx=SimpleNamespace(
            owner_leases=owner_leases(async_redis), owner_id=OWNER, db=db, audio_dir=audio_dir,
        ),
        background_loop_registry=BackgroundLoopRegistry(tuple(BackgroundLoopName)),
    ))


def _running_job_of(factory, owner_id: str) -> str:
    with factory() as session:
        job = create_job(session, JobType.CHAT, owner_id=owner_id)
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
    _running_job_of(pg_factory, ANOTHER)
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


def test_the_owner_lease_shows_failing_while_only_the_old_key_of_this_process_lives(
    monkeypatch, pg_factory, tmp_path,
) -> None:
    server = make_fake_async_redis()
    arrange_fake_async_redis(server, settle_owner_leases)
    arrange_fake_async_redis(
        server, lambda fake: fake.set(old_owner_key(REDIS_KEY_PREFIX, OWNER), "1"),
    )

    status = _own_lease_status_after_the_ticks(monkeypatch, server, pg_factory, tmp_path)

    assert status is BackgroundLoopStatus.FAILING


def test_the_owner_lease_shows_failing_while_redis_is_down(
    monkeypatch, pg_factory, tmp_path,
) -> None:
    status = _own_lease_status_after_the_ticks(
        monkeypatch, _UnreachableRedis(), pg_factory, tmp_path,
    )

    assert status is BackgroundLoopStatus.FAILING


def test_the_lapse_loop_ends_the_jobs_of_an_owner_whose_lease_ended(
    pg_factory, tmp_path,
) -> None:
    server = make_fake_async_redis()
    job_id = _running_job_of(pg_factory, ANOTHER)
    app = _loop_app(server, pg_factory, tmp_path)

    async def end_the_lease_of_another_and_wait_for_its_job() -> tuple[str, str | None]:
        await settle_owner_leases(server)
        leases = owner_leases(server)
        await leases.end(ANOTHER, (await leases.renew(ANOTHER)).generation)
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


def test_a_cover_another_process_failed_while_this_lease_had_lapsed_leaves_no_staging(
    pg_factory, tmp_path,
) -> None:
    with pg_factory() as session:
        cover = create_job(session, JobType.COVER, owner_id=OWNER)
        for status in (JobStatus.RUNNING, JobStatus.FAILED):
            assert update_job_status(session, cover.id, JobStatusUpdate(status))
        session.commit()
        staging = cover_staging_path(tmp_path, cover.id)
    staging.mkdir(parents=True)
    ctx = SimpleNamespace(db=pg_factory, audio_dir=tmp_path)

    asyncio.run(reconcile_ended_covers(ctx))

    assert not staging.exists()
