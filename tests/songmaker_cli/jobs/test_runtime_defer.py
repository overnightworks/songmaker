"""A job the GPU hold puts back in the queue waits one poll for its next claim."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from support.job_owner import an_owner

from songmaker_cli.db.queries.jobs import claim_queued_job, create_job, get_job
from songmaker_cli.job_payloads import GeneratePayload
from songmaker_cli.job_timing import GPU_HOLD_POLL_INTERVAL_SECONDS
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.jobs._runtime import _defer_job
from songmaker_cli.jobs.generation import _requeue_generation
from songmaker_cli.jobs.generation_request import GenerationJobRequest
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


def test_a_new_job_may_be_claimed_from_the_moment_it_is_created(pg_factory) -> None:
    before = utcnow()
    with pg_factory() as session:
        job_id = create_job(session, JobType.GENERATE).id
        session.commit()
    after = utcnow()

    with pg_factory() as session:
        assert before <= get_job(session, job_id).run_after <= after


def test_a_generation_requeued_after_some_takes_stores_the_takes_it_has_left(
    pg_factory, tmp_path: Path,
) -> None:
    payload = GeneratePayload(
        song_id="song", version_id="version", count=3, user_id="user",
        seed=None, target_model="sft", task_params=None,
    )
    with pg_factory() as session:
        job_id = create_job(session, JobType.GENERATE, payload=payload).id
        claim_queued_job(session, job_id, WORKER)
        session.commit()
    request = GenerationJobRequest(
        job_id=job_id, audio_dir=tmp_path, data_dir=tmp_path, repaint_params=None,
        cover_params=None, **payload.model_dump(exclude={"job_type", "task_params"}),
    )
    redis = MagicMock(enqueue_job=AsyncMock())

    asyncio.run(_requeue_generation(request.with_takes_left(2), redis, pg_factory))

    with pg_factory() as session:
        stored = get_job(session, job_id).payload
    assert stored == payload.model_copy(update={"count": 2})
    queued_count = redis.enqueue_job.await_args.args[1 + 3]
    assert queued_count == stored.count
