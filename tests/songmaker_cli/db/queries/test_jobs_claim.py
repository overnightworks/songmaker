"""A job is claimed once: the queued row moves to running for one owner, or the claim fails."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from support.job_owner import an_owner

from songmaker_cli.db.queries.jobs import (
    JobStatusUpdate,
    claim_next_queued_job,
    claim_queued_job,
    create_job,
    get_job,
    update_job_status,
)
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.timestamps import utcnow

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


def _a_job_due_in(session, seconds: float, job_type: str = JobType.SCORE):
    job = create_job(session, job_type)
    job.run_after = utcnow() + timedelta(seconds=seconds)
    session.flush()
    return job


def test_the_next_queued_job_of_a_type_runs_for_the_claimer_with_its_generation(pg_factory) -> None:
    with pg_factory() as session:
        job = _a_job_due_in(session, -1)

        claimed = claim_next_queued_job(session, FIRST, JobType.SCORE)

        assert (claimed.id, claimed.status, claimed.owner_id, claimed.owner_generation) == (
            job.id, JobStatus.RUNNING, "first-owner", "first-generation",
        )


def test_the_job_due_first_is_claimed_first(pg_factory) -> None:
    with pg_factory() as session:
        later = _a_job_due_in(session, -1)
        earlier = _a_job_due_in(session, -60)

        order = [claim_next_queued_job(session, FIRST, JobType.SCORE).id for _ in range(2)]

        assert order == [earlier.id, later.id]


def test_a_job_whose_wait_has_not_ended_is_not_claimed_until_it_has(pg_factory) -> None:
    with pg_factory() as session:
        job = _a_job_due_in(session, 3600)

        before = claim_next_queued_job(session, FIRST, JobType.SCORE)
        job.run_after = utcnow() - timedelta(seconds=1)
        session.flush()
        after = claim_next_queued_job(session, FIRST, JobType.SCORE)

        assert (before, after.id) == (None, job.id)


def test_a_cancelled_job_is_never_claimed_though_its_wait_has_ended(pg_factory) -> None:
    with pg_factory() as session:
        job = _a_job_due_in(session, -1)
        update_job_status(session, job.id, JobStatusUpdate(JobStatus.CANCELLED))

        assert claim_next_queued_job(session, FIRST, JobType.SCORE) is None
        assert get_job(session, job.id).status == JobStatus.CANCELLED


def test_a_job_without_a_wait_is_left_to_its_queue_message(pg_factory) -> None:
    with pg_factory() as session:
        job = _a_job_due_in(session, 0)
        job.run_after = None
        session.flush()

        assert claim_next_queued_job(session, FIRST, JobType.SCORE) is None


def test_only_the_asked_type_is_claimed(pg_factory) -> None:
    with pg_factory() as session:
        _a_job_due_in(session, -1, JobType.GENERATE)

        assert claim_next_queued_job(session, FIRST, JobType.SCORE) is None


def test_a_running_job_is_not_claimed_again(pg_factory) -> None:
    with pg_factory() as session:
        _a_job_due_in(session, -1)
        claim_next_queued_job(session, FIRST, JobType.SCORE)

        assert claim_next_queued_job(session, SECOND, JobType.SCORE) is None


def test_two_claimers_that_have_not_committed_get_different_jobs(pg_factory) -> None:
    with pg_factory() as setup:
        ids = {_a_job_due_in(setup, -1).id, _a_job_due_in(setup, -1).id}
        setup.commit()
    with pg_factory() as first_session, pg_factory() as second_session:
        first = claim_next_queued_job(first_session, FIRST, JobType.SCORE)

        second = claim_next_queued_job(second_session, SECOND, JobType.SCORE)

        assert ids == {first.id, second.id}
