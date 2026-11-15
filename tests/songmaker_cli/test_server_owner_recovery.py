"""Web processes and music workers: only the jobs of an owner that is gone fail."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from redis import Redis
from support.app_processes import (
    MusicWorkerProcess,
    WebProcess,
    WebProcesses,
    leased_owner_ids,
    poll_until,
)

from songmaker_cli.constants import BACKGROUND_LOOP_FAILURE_THRESHOLD
from songmaker_cli.cover_runner import cover_staging_path
from songmaker_cli.db.models import Job
from songmaker_cli.db.queries.jobs import (
    JOB_ERROR_SERVER_RESTARTED,
    JobStatusUpdate,
    create_job,
    update_job_status,
)
from songmaker_cli.job_timing import (
    OWNER_GONE_CHECK_INTERVAL_SECONDS,
    OWNER_LEASE_REFRESH_SECONDS,
    OWNER_LEASE_TTL_SECONDS,
)
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.lifecycle import OWNER_REAPER_FAILURE_MESSAGE
from songmaker_cli.worker_liveness import owner_lease_key

MARGIN_SECONDS = 5.0
CRASH_DEADLINE_SECONDS = 30.0
LOOP_FAILING_DEADLINE_SECONDS = 40.0


@dataclass(frozen=True)
class RunningJobs:
    """A chat job and a cover job one owner is running, and what the cover left on disk."""

    chat_id: str
    cover_id: str
    staging_dir: Path

    @property
    def ids(self) -> tuple[str, str]:
        return (self.chat_id, self.cover_id)


@pytest.fixture
def redis_client(redis_url: str):
    with Redis.from_url(redis_url, decode_responses=True) as client:
        yield client


@pytest.fixture(autouse=True)
def lease_ttl_has_passed_on_the_server(redis_client: Redis) -> None:
    """An absent lease reads dead only on a server that has run for the lease TTL."""
    assert poll_until(
        lambda: redis_client.info("server")["uptime_in_seconds"] >= OWNER_LEASE_TTL_SECONDS,
        deadline_seconds=OWNER_LEASE_TTL_SECONDS + MARGIN_SECONDS,
    )


def _start_owner(cluster: WebProcesses, redis_client: Redis, name: str) -> tuple[WebProcess, str]:
    """Start a process and return it with the owner id its lease names."""
    before = leased_owner_ids(redis_client)
    process = cluster.start(name)
    [owner_id] = leased_owner_ids(redis_client) - before
    return process, owner_id


def _seed_running_jobs(factory, cluster: WebProcesses, owner_id: str) -> RunningJobs:
    with factory() as session:
        chat = create_job(session, JobType.CHAT, owner_id=owner_id)
        cover = create_job(session, JobType.COVER, owner_id=owner_id)
        for job in (chat, cover):
            assert update_job_status(session, job.id, JobStatusUpdate(JobStatus.RUNNING))
        session.commit()
        jobs = RunningJobs(chat.id, cover.id, cover_staging_path(cluster.audio_dir, cover.id))
    jobs.staging_dir.mkdir(parents=True)
    return jobs


def _statuses(factory, job_ids) -> list[str]:
    with factory() as session:
        return [session.get(Job, job_id).status for job_id in job_ids]


def _failed_with_the_restart_verdict(factory, job_ids) -> bool:
    restarted = (JobStatus.FAILED, JOB_ERROR_SERVER_RESTARTED.error_type)
    with factory() as session:
        return all(
            (job.status, job.error_type) == restarted
            for job in (session.get(Job, job_id) for job_id in job_ids)
        )


def _is_reaped(factory, jobs: RunningJobs) -> bool:
    return _failed_with_the_restart_verdict(factory, jobs.ids) and not jobs.staging_dir.exists()


def _owner_pass_failures(process: WebProcess) -> int:
    return process.log_text().count(OWNER_REAPER_FAILURE_MESSAGE)


def test_a_process_that_starts_ends_the_jobs_of_an_owner_that_is_gone_and_no_live_one(
    web_cluster, redis_client,
) -> None:
    cluster, factory = web_cluster
    _, owner_a = _start_owner(cluster, redis_client, "a")
    jobs_of_a = _seed_running_jobs(factory, cluster, owner_a)
    jobs_of_a_ghost = _seed_running_jobs(factory, cluster, uuid.uuid4().hex)

    _start_owner(cluster, redis_client, "b")

    assert (
        _statuses(factory, jobs_of_a.ids),
        _is_reaped(factory, jobs_of_a_ghost),
        jobs_of_a.staging_dir.is_dir(),
    ) == ([JobStatus.RUNNING] * 2, True, True)


@pytest.fixture
def a_and_b(web_cluster, redis_client):
    """A and B on one database and Redis; A runs the seeded jobs, B is the observer."""
    cluster, factory = web_cluster
    process_a, owner_a = _start_owner(cluster, redis_client, "a")
    process_b, _ = _start_owner(cluster, redis_client, "b")
    return cluster, factory, process_a, owner_a, process_b, _seed_running_jobs(
        factory, cluster, owner_a,
    )


def test_a_clean_stop_of_one_process_ends_its_jobs_on_the_other_within_one_tick(
    a_and_b, redis_client,
) -> None:
    cluster, factory, process_a, owner_a, _, jobs = a_and_b

    process_a.stop()

    assert redis_client.exists(owner_lease_key(owner_a)) == 0
    assert poll_until(
        lambda: _is_reaped(factory, jobs),
        deadline_seconds=OWNER_GONE_CHECK_INTERVAL_SECONDS + MARGIN_SECONDS,
    )


def test_a_crash_of_one_process_ends_its_jobs_on_the_other_once_the_lease_has_lapsed(
    a_and_b,
) -> None:
    _, factory, process_a, _, _, jobs = a_and_b

    process_a.kill()

    assert poll_until(lambda: _is_reaped(factory, jobs), deadline_seconds=CRASH_DEADLINE_SECONDS)


def test_a_crash_with_redis_unreachable_ends_nothing_until_redis_answers_again(
    proxied_cluster, redis_client,
) -> None:
    cluster, factory, proxy = proxied_cluster
    process_a, owner_a = _start_owner(cluster, redis_client, "a")
    process_b, _ = _start_owner(cluster, redis_client, "b")
    jobs = _seed_running_jobs(factory, cluster, owner_a)

    proxy.cut()
    process_a.kill()

    assert poll_until(
        lambda: _owner_pass_failures(process_b) >= BACKGROUND_LOOP_FAILURE_THRESHOLD,
        deadline_seconds=LOOP_FAILING_DEADLINE_SECONDS,
    )
    assert _statuses(factory, jobs.ids) == [JobStatus.RUNNING] * 2
    proxy.restore()
    assert poll_until(
        lambda: _is_reaped(factory, jobs),
        deadline_seconds=OWNER_GONE_CHECK_INTERVAL_SECONDS + MARGIN_SECONDS,
    )


def test_a_redis_that_restarts_empty_ends_nothing_and_gets_the_live_lease_back(
    proxied_cluster, redis_client,
) -> None:
    cluster, factory, proxy = proxied_cluster
    _, owner_a = _start_owner(cluster, redis_client, "a")
    _start_owner(cluster, redis_client, "b")
    jobs = _seed_running_jobs(factory, cluster, owner_a)
    restarted_at = time.monotonic()

    proxy.restart_empty()

    ghost = _seed_running_jobs(factory, cluster, uuid.uuid4().hex)

    assert poll_until(
        lambda: redis_client.exists(owner_lease_key(owner_a)) == 1,
        deadline_seconds=OWNER_LEASE_REFRESH_SECONDS + MARGIN_SECONDS,
    )
    assert poll_until(lambda: _is_reaped(factory, ghost), deadline_seconds=CRASH_DEADLINE_SECONDS)
    assert time.monotonic() - restarted_at >= OWNER_LEASE_TTL_SECONDS - 1
    assert _statuses(factory, jobs.ids) == [JobStatus.RUNNING] * 2


def _seed_running_worker_jobs(factory, owner_id: str) -> tuple[str, str]:
    """A generation job and a LoRA training job the owner is running."""
    with factory() as session:
        jobs = [
            create_job(session, job_type, owner_id=owner_id)
            for job_type in (JobType.GENERATE, JobType.LORA_TRAINING)
        ]
        for job in jobs:
            assert update_job_status(session, job.id, JobStatusUpdate(JobStatus.RUNNING))
        session.commit()
        generation_id, training_id = jobs[0].id, jobs[1].id
    return generation_id, training_id


@dataclass(frozen=True)
class MusicWorkers:
    """Two music workers, a web process that reaps for them, and the jobs each is running."""

    factory: object
    worker_a: MusicWorkerProcess
    worker_b: MusicWorkerProcess
    jobs_of_a: tuple[str, str]
    jobs_of_b: tuple[str, str]


@pytest.fixture
def music_workers(web_cluster) -> MusicWorkers:
    cluster, factory = web_cluster
    worker_a = cluster.start_music_worker("worker-a")
    worker_b = cluster.start_music_worker("worker-b")
    cluster.start("web")
    return MusicWorkers(
        factory,
        worker_a,
        worker_b,
        _seed_running_worker_jobs(factory, worker_a.owner_id),
        _seed_running_worker_jobs(factory, worker_b.owner_id),
    )


def test_a_music_worker_that_starts_leaves_the_jobs_of_a_running_one_alone(web_cluster) -> None:
    cluster, factory = web_cluster
    worker_a = cluster.start_music_worker("worker-a")
    jobs_of_a = _seed_running_worker_jobs(factory, worker_a.owner_id)

    cluster.start_music_worker("worker-b")

    assert _statuses(factory, jobs_of_a) == [JobStatus.RUNNING] * 2


def test_a_clean_stop_of_one_music_worker_ends_its_jobs_within_one_tick_and_no_other(
    music_workers: MusicWorkers, redis_client,
) -> None:
    music_workers.worker_a.stop()

    assert redis_client.exists(owner_lease_key(music_workers.worker_a.owner_id)) == 0
    assert poll_until(
        lambda: _failed_with_the_restart_verdict(music_workers.factory, music_workers.jobs_of_a),
        deadline_seconds=OWNER_GONE_CHECK_INTERVAL_SECONDS + MARGIN_SECONDS,
    )
    assert _statuses(music_workers.factory, music_workers.jobs_of_b) == [JobStatus.RUNNING] * 2


def test_a_crash_of_one_music_worker_ends_its_jobs_once_the_lease_has_lapsed_and_no_other(
    music_workers: MusicWorkers,
) -> None:
    music_workers.worker_a.kill()

    assert poll_until(
        lambda: _failed_with_the_restart_verdict(music_workers.factory, music_workers.jobs_of_a),
        deadline_seconds=CRASH_DEADLINE_SECONDS,
    )
    assert _statuses(music_workers.factory, music_workers.jobs_of_b) == [JobStatus.RUNNING] * 2
