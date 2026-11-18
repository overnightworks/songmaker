"""A job the GPU hold puts back in the queue waits one poll for its next claim."""

from __future__ import annotations

from datetime import timedelta

from support.job_owner import an_owner

from songmaker_cli.db.queries.jobs import claim_queued_job, create_job, get_job
from songmaker_cli.job_timing import GPU_HOLD_POLL_INTERVAL_SECONDS
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.jobs._runtime import _defer_job
from songmaker_cli.messages import message
from songmaker_cli.timestamps import utcnow

REASON = message("jobWait.voiceTraining")
WORKER = an_owner("worker")


def test_a_deferred_job_is_queued_without_an_owner_and_names_why_it_waits(pg_factory) -> None:
    with pg_factory() as session:
        job_id = create_job(session, JobType.GENERATE).id
        claim_queued_job(session, job_id, WORKER)
        session.commit()

    _defer_job(pg_factory, job_id, REASON)

    with pg_factory() as session:
        job = get_job(session, job_id)
        assert (job.status, job.owner_id, job.owner_generation, job.queue_reason_message) == (
            JobStatus.QUEUED, None, None, REASON,
        )


def test_a_deferred_job_waits_one_poll_interval_from_now(pg_factory) -> None:
    with pg_factory() as session:
        job_id = create_job(session, JobType.GENERATE).id
        session.commit()
    before = utcnow()

    _defer_job(pg_factory, job_id, REASON)

    after = utcnow()
    wait = timedelta(seconds=GPU_HOLD_POLL_INTERVAL_SECONDS)
    with pg_factory() as session:
        assert before + wait <= get_job(session, job_id).run_after <= after + wait


def test_a_deferred_job_can_be_claimed_again(pg_factory) -> None:
    with pg_factory() as session:
        job_id = create_job(session, JobType.GENERATE).id
        claim_queued_job(session, job_id, WORKER)
        session.commit()
    _defer_job(pg_factory, job_id, REASON)

    with pg_factory() as session:
        assert claim_queued_job(session, job_id, WORKER) is True
