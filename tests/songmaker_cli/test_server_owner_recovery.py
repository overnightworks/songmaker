"""Web processes and music workers: only the jobs of an owner that is gone fail."""

from __future__ import annotations

import signal
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
    age_the_owner_lease_epoch,
    end_the_owner_lease,
    leased_owner_ids,
    owner_lease_generation,
    poll_until,
)
from support.job_owner import an_owner, create_job_of_unstamped_owner
from support.web_cluster_world import start_owner

from songmaker_cli.constants import BACKGROUND_LOOP_FAILURE_THRESHOLD, REDIS_KEY_PREFIX
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
from songmaker_cli.owner_lease_old_key import old_owner_key

MARGIN_SECONDS = 5.0
CRASH_DEADLINE_SECONDS = 30.0
LOOP_FAILING_DEADLINE_SECONDS = 40.0
PREVIOUS_RELEASE_SECONDS = 120


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
def lease_span_has_passed_on_the_server(redis_client: Redis) -> None:
    """An absent lease reads gone only on a server that has run for the lease span."""
    age_the_owner_lease_epoch(redis_client)


def _seed_running_jobs(factory, cluster: WebProcesses, owner_id: str) -> RunningJobs:
    with factory() as session:
        chat = create_job_of_unstamped_owner(session, JobType.CHAT, owner_id)
        cover = create_job_of_unstamped_owner(session, JobType.COVER, owner_id)
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
    _, owner_a = start_owner(cluster, redis_client, "a")
    jobs_of_a = _seed_running_jobs(factory, cluster, owner_a)
    jobs_of_a_ghost = _seed_running_jobs(factory, cluster, uuid.uuid4().hex)

    start_owner(cluster, redis_client, "b")

    assert (
        _statuses(factory, jobs_of_a.ids),
        _is_reaped(factory, jobs_of_a_ghost),
        jobs_of_a.staging_dir.is_dir(),
    ) == ([JobStatus.RUNNING] * 2, True, True)


def test_an_owner_of_the_previous_release_keeps_its_jobs_when_a_process_starts(
    web_cluster, redis_client,
) -> None:
    cluster, factory = web_cluster
    previous_owner = uuid.uuid4().hex
    redis_client.set(
        old_owner_key(REDIS_KEY_PREFIX, previous_owner), "1", ex=PREVIOUS_RELEASE_SECONDS,
    )
    jobs = _seed_running_jobs(factory, cluster, previous_owner)

    start_owner(cluster, redis_client, "a")

    assert _statuses(factory, jobs.ids) == [JobStatus.RUNNING] * 2


def test_a_process_shows_the_previous_release_its_old_key_until_it_stops(
    web_cluster, redis_client,
) -> None:
    cluster, _ = web_cluster
    process, owner = start_owner(cluster, redis_client, "a")
    key = old_owner_key(REDIS_KEY_PREFIX, owner)

    assert redis_client.exists(key) == 1
    process.stop()
    assert redis_client.exists(key) == 0


@pytest.fixture
def a_and_b(web_cluster, redis_client):
    """A and B on one database and Redis; A runs the seeded jobs, B is the observer."""
    cluster, factory = web_cluster
    process_a, owner_a = start_owner(cluster, redis_client, "a")
    process_b, _ = start_owner(cluster, redis_client, "b")
    return cluster, factory, process_a, owner_a, process_b, _seed_running_jobs(
        factory, cluster, owner_a,
    )


def test_a_clean_stop_of_one_process_ends_its_jobs_on_the_other_within_one_tick(
    a_and_b, redis_client,
) -> None:
    cluster, factory, process_a, owner_a, _, jobs = a_and_b

    process_a.stop()

    assert owner_a not in leased_owner_ids(redis_client)
    assert poll_until(
        lambda: _is_reaped(factory, jobs),
        deadline_seconds=OWNER_GONE_CHECK_INTERVAL_SECONDS + MARGIN_SECONDS,
    )


def _seed_running_job_of_generation(factory, owner_id: str, generation: str) -> str:
    with factory() as session:
        job = create_job(session, JobType.CHAT, owner=an_owner(owner_id, generation))
        assert update_job_status(session, job.id, JobStatusUpdate(JobStatus.RUNNING))
        session.commit()
        return job.id


def test_a_lease_that_lapsed_and_started_again_ends_the_jobs_of_its_old_generation_only(
    a_and_b, redis_client,
) -> None:
    cluster, factory, _, owner_a, _, _ = a_and_b
    lapsed_generation = owner_lease_generation(redis_client, owner_a)
    job_of_the_lapsed_generation = _seed_running_job_of_generation(
        factory, owner_a, lapsed_generation,
    )

    end_the_owner_lease(redis_client, owner_a, lapsed_generation)
    assert poll_until(
        lambda: _failed_with_the_restart_verdict(factory, [job_of_the_lapsed_generation]),
        deadline_seconds=OWNER_GONE_CHECK_INTERVAL_SECONDS + MARGIN_SECONDS,
    )
    assert poll_until(
        lambda: owner_lease_generation(redis_client, owner_a) not in (None, lapsed_generation),
        deadline_seconds=OWNER_LEASE_REFRESH_SECONDS + MARGIN_SECONDS,
    )
    job_of_the_new_generation = _seed_running_job_of_generation(
        factory, owner_a, owner_lease_generation(redis_client, owner_a),
    )

    ghost = _seed_running_jobs(factory, cluster, uuid.uuid4().hex)

    assert poll_until(
        lambda: _is_reaped(factory, ghost),
        deadline_seconds=OWNER_GONE_CHECK_INTERVAL_SECONDS + MARGIN_SECONDS,
    )
    assert _statuses(factory, [job_of_the_new_generation]) == [JobStatus.RUNNING]


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
    process_a, owner_a = start_owner(cluster, redis_client, "a")
    process_b, _ = start_owner(cluster, redis_client, "b")
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


def test_a_stop_with_redis_unreachable_still_shuts_the_process_down(
    proxied_cluster, redis_client,
) -> None:
    cluster, _, proxy = proxied_cluster
    process, _ = start_owner(cluster, redis_client, "a")

    proxy.cut()
    process.stop()

    assert process.process.returncode != -signal.SIGKILL, "the stop needed the kill"


def test_a_redis_that_restarts_empty_ends_nothing_and_gets_the_live_lease_back(
    proxied_cluster, redis_client,
) -> None:
    cluster, factory, proxy = proxied_cluster
    _, owner_a = start_owner(cluster, redis_client, "a")
    start_owner(cluster, redis_client, "b")
    jobs = _seed_running_jobs(factory, cluster, owner_a)
    restarted_at = time.monotonic()

    proxy.restart_empty()

    ghost = _seed_running_jobs(factory, cluster, uuid.uuid4().hex)

    assert poll_until(
        lambda: owner_a in leased_owner_ids(redis_client),
        deadline_seconds=OWNER_LEASE_REFRESH_SECONDS + MARGIN_SECONDS,
    )
    assert poll_until(lambda: _is_reaped(factory, ghost), deadline_seconds=CRASH_DEADLINE_SECONDS)
    assert time.monotonic() - restarted_at >= OWNER_LEASE_TTL_SECONDS - 1
    assert _statuses(factory, jobs.ids) == [JobStatus.RUNNING] * 2


WORKER_JOB_TYPES = (
    JobType.GENERATE,
    JobType.LORA_TRAINING,
    JobType.SCORE,
    JobType.LOAD_MODEL_ON_WORKER,
    JobType.DOWNLOAD_MODEL_ON_WORKER,
)


def _seed_running_worker_jobs(factory, owner_id: str) -> tuple[str, ...]:
    """One running job of each type a worker executes, owned by ``owner_id``."""
    with factory() as session:
        jobs = [
            create_job_of_unstamped_owner(session, job_type, owner_id)
            for job_type in WORKER_JOB_TYPES
        ]
        for job in jobs:
            assert update_job_status(session, job.id, JobStatusUpdate(JobStatus.RUNNING))
        session.commit()
        return tuple(job.id for job in jobs)


@dataclass(frozen=True)
class MusicWorkers:
    """Two music workers, a web process that reaps for them, and the jobs each is running."""

    factory: object
    worker_a: MusicWorkerProcess
    worker_b: MusicWorkerProcess
    jobs_of_a: tuple[str, ...]
    jobs_of_b: tuple[str, ...]


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

    assert _statuses(factory, jobs_of_a) == [JobStatus.RUNNING] * len(WORKER_JOB_TYPES)


def test_a_clean_stop_of_one_music_worker_ends_its_jobs_within_one_tick_and_no_other(
    music_workers: MusicWorkers, redis_client,
) -> None:
    music_workers.worker_a.stop()

    assert music_workers.worker_a.owner_id not in leased_owner_ids(redis_client)
    assert poll_until(
        lambda: _failed_with_the_restart_verdict(music_workers.factory, music_workers.jobs_of_a),
        deadline_seconds=OWNER_GONE_CHECK_INTERVAL_SECONDS + MARGIN_SECONDS,
    )
    assert _statuses(music_workers.factory, music_workers.jobs_of_b) == (
        [JobStatus.RUNNING] * len(WORKER_JOB_TYPES)
    )


def test_a_crash_of_one_music_worker_ends_its_jobs_once_the_lease_has_lapsed_and_no_other(
    music_workers: MusicWorkers,
) -> None:
    music_workers.worker_a.kill()

    assert poll_until(
        lambda: _failed_with_the_restart_verdict(music_workers.factory, music_workers.jobs_of_a),
        deadline_seconds=CRASH_DEADLINE_SECONDS,
    )
    assert _statuses(music_workers.factory, music_workers.jobs_of_b) == (
        [JobStatus.RUNNING] * len(WORKER_JOB_TYPES)
    )
