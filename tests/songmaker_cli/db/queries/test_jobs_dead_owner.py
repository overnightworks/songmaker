"""A job names the process that runs it; only an owner read as gone ends its jobs."""

from __future__ import annotations

import pytest

from songmaker_cli.db.models import Job
from songmaker_cli.db.queries.jobs import (
    JOB_ERROR_SERVER_RESTARTED,
    JobStatusUpdate,
    active_job_owner_ids,
    claim_next_cover_job,
    create_job,
    recover_jobs_of_dead_owners,
    recover_stale_jobs_by_age_and_type,
    recover_stale_jobs_by_type,
    update_job_status,
)
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.worker_liveness import WorkerLiveness

GONE = "owner-gone"
HERE = "owner-here"
UNREAD = "owner-unread"


def _running_job(session, job_type: JobType, owner_id: str | None) -> str:
    job = create_job(session, job_type, owner_id=owner_id)
    assert update_job_status(session, job.id, JobStatusUpdate(JobStatus.RUNNING))
    return job.id


def _outcome(session, job_id: str) -> tuple[str, str | None]:
    job = session.get(Job, job_id)
    session.refresh(job)
    return job.status, job.error_type


def test_only_the_jobs_of_a_dead_owner_fail_with_the_restart_verdict(pg_factory) -> None:
    with pg_factory() as session:
        gone = _running_job(session, JobType.CHAT, GONE)
        gone_cover = _running_job(session, JobType.COVER, GONE)
        here = _running_job(session, JobType.CHAT, HERE)
        unread = _running_job(session, JobType.CHAT, UNREAD)
        missing_from_the_map = _running_job(session, JobType.CHAT, "owner-not-asked")
        unowned = _running_job(session, JobType.CHAT, None)

        recovered = recover_jobs_of_dead_owners(session, {
            GONE: WorkerLiveness.DEAD, HERE: WorkerLiveness.ALIVE, UNREAD: WorkerLiveness.UNKNOWN,
        })

        assert recovered == {JobType.CHAT: 1, JobType.COVER: 1}
        assert [_outcome(session, job_id) for job_id in (gone, gone_cover)] == [
            (JobStatus.FAILED, JOB_ERROR_SERVER_RESTARTED.error_type),
        ] * 2
        still_running = (here, unread, missing_from_the_map)
        assert [_outcome(session, job_id)[0] for job_id in still_running] == [JobStatus.RUNNING] * 3
        assert _outcome(session, unowned)[0] == JobStatus.RUNNING


def test_a_queued_job_of_a_dead_owner_fails_too_and_a_finished_one_is_left(pg_factory) -> None:
    with pg_factory() as session:
        queued = create_job(session, JobType.CHAT, owner_id=GONE).id
        finished = _running_job(session, JobType.CHAT, GONE)
        update_job_status(session, finished, JobStatusUpdate(JobStatus.COMPLETED))

        recover_jobs_of_dead_owners(session, {GONE: WorkerLiveness.DEAD})

        assert (_outcome(session, queued)[0], _outcome(session, finished)[0]) == (
            JobStatus.FAILED, JobStatus.COMPLETED,
        )


def test_the_owners_asked_about_are_those_of_active_jobs_only(pg_factory) -> None:
    with pg_factory() as session:
        _running_job(session, JobType.CHAT, HERE)
        _running_job(session, JobType.CHAT, None)
        done = _running_job(session, JobType.CHAT, GONE)
        update_job_status(session, done, JobStatusUpdate(JobStatus.COMPLETED))

        assert active_job_owner_ids(session) == {HERE}


def test_the_submission_path_ends_the_dead_owners_job_through_the_same_verdict(pg_factory) -> None:
    with pg_factory() as session:
        gone = _running_job(session, JobType.CHAT, GONE)

        recover_stale_jobs_by_age_and_type(session, owner_liveness={GONE: WorkerLiveness.DEAD})

        assert _outcome(session, gone) == (
            JobStatus.FAILED, JOB_ERROR_SERVER_RESTARTED.error_type,
        )


@pytest.mark.parametrize("owner_liveness", [None, {GONE: WorkerLiveness.UNKNOWN}])
def test_the_age_reaper_without_a_dead_owner_leaves_a_fresh_job_alone(
    pg_factory, owner_liveness,
) -> None:
    with pg_factory() as session:
        gone = _running_job(session, JobType.CHAT, GONE)

        recover_stale_jobs_by_age_and_type(session, owner_liveness=owner_liveness)

        assert _outcome(session, gone)[0] == JobStatus.RUNNING


def test_the_remaining_bulk_recovery_uses_the_one_restart_verdict(pg_factory) -> None:
    with pg_factory() as session:
        job = _running_job(session, JobType.GENERATE, None)

        recover_stale_jobs_by_type(session, {JobType.GENERATE: {JobStatus.RUNNING}})

        failed = session.get(Job, job)
        session.refresh(failed)
        assert (failed.error, failed.error_type) == (
            JOB_ERROR_SERVER_RESTARTED.error, JOB_ERROR_SERVER_RESTARTED.error_type,
        )


def test_claiming_a_cover_job_names_the_claimer_as_its_owner(pg_factory) -> None:
    with pg_factory() as session:
        queued = create_job(session, JobType.COVER)

        claimed = claim_next_cover_job(session, HERE)

        assert (claimed.id, claimed.owner_id) == (queued.id, HERE)
