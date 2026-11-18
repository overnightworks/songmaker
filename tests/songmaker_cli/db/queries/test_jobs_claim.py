"""A job is claimed once: the queued row moves to running for one owner, or the claim fails."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from support.job_owner import an_owner

from songmaker_cli.db.queries.jobs import (
    JobStatusUpdate,
    claim_queued_job,
    create_job,
    get_job,
    update_job_status,
)
from songmaker_cli.job_types import JobStatus, JobType

FIRST = an_owner("first-owner", "first-generation")
SECOND = an_owner("second-owner", "second-generation")


def test_claiming_a_queued_job_runs_it_for_the_claimer(pg_factory) -> None:
    with pg_factory() as session:
        job = create_job(session, JobType.GENERATE)

        claimed = claim_queued_job(session, job.id, FIRST)

        row = get_job(session, job.id)
        assert (claimed, row.status, row.owner_id, row.owner_generation) == (
            True, JobStatus.RUNNING, "first-owner", "first-generation",
        )


def test_a_second_claim_of_the_same_job_fails_and_leaves_the_first_owner(pg_factory) -> None:
    with pg_factory() as session:
        job = create_job(session, JobType.GENERATE)
        claim_queued_job(session, job.id, FIRST)

        claimed_again = claim_queued_job(session, job.id, SECOND)

        assert (claimed_again, get_job(session, job.id).owner_id) == (False, "first-owner")


@pytest.mark.parametrize(
    "status", [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.PARTIAL, JobStatus.CANCELLED],
)
def test_a_job_that_ended_cannot_be_claimed(pg_factory, status) -> None:
    with pg_factory() as session:
        job = create_job(session, JobType.GENERATE)
        update_job_status(session, job.id, JobStatusUpdate(status))

        claimed = claim_queued_job(session, job.id, FIRST)

        assert (claimed, get_job(session, job.id).status) == (False, status)


def test_a_job_without_a_row_cannot_be_claimed(pg_factory) -> None:
    with pg_factory() as session:
        assert claim_queued_job(session, "no-such-job", FIRST) is False


def test_a_job_put_back_in_the_queue_with_a_wait_can_be_claimed_again(pg_factory) -> None:
    wait_ends = datetime.now(timezone.utc) + timedelta(seconds=5)
    with pg_factory() as session:
        job = create_job(session, JobType.GENERATE)
        claim_queued_job(session, job.id, FIRST)
        update_job_status(
            session, job.id, JobStatusUpdate(JobStatus.QUEUED, run_after=wait_ends),
        )
        queued = get_job(session, job.id)
        waiting = (queued.status, queued.owner_id, queued.owner_generation, queued.run_after)

        claimed = claim_queued_job(session, job.id, SECOND)

        row = get_job(session, job.id)
        assert (waiting, claimed, row.owner_id, row.run_after) == (
            (JobStatus.QUEUED, None, None, wait_ends), True, "second-owner", None,
        )
