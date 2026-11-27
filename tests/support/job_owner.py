"""A process that owns jobs, for tests that run a job function without a lease in Redis."""

from __future__ import annotations

from unittest.mock import AsyncMock

from tandem import Hold

from songmaker_cli.db.queries.jobs import create_job, get_job
from songmaker_cli.worker_liveness import JobOwner


def an_owner(owner_id: str, generation: str = "generation-1") -> JobOwner:
    return JobOwner(owner_id, Hold(generation))


def given_owner_redis(worker, client=None):
    """``worker`` with the Redis client a started worker owns; a mock unless one is given."""
    worker._owner_redis = AsyncMock() if client is None else client
    return worker


def create_job_of_unstamped_owner(session, job_type: str, owner_id: str, **fields):
    """A job as written before generations were stored: its owner without a generation."""
    job = create_job(session, job_type, **fields)
    job.owner_id = owner_id
    session.flush()
    return job


def create_job_of_owner(session, job_type: str, owner: JobOwner | str, **fields):
    """A job of ``owner``; one given as a bare id names no generation, as a legacy row does."""
    if isinstance(owner, str):
        return create_job_of_unstamped_owner(session, job_type, owner, **fields)
    return create_job(session, job_type, owner=owner, **fields)


def stored_payload(factory, job_id: str):
    """The arguments the job's row holds: what a worker runs the job with."""
    with factory() as session:
        return get_job(session, job_id).payload
