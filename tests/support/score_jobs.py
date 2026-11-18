"""Queued score jobs for tests that claim or run them."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from unittest.mock import patch

import pytest

from songmaker_cli.db.models import Job
from songmaker_cli.db.queries.jobs import create_job
from songmaker_cli.job_payloads import ScorePayload
from songmaker_cli.job_queue import JobQueue
from songmaker_cli.job_types import JobType
from songmaker_cli.timestamps import utcnow

A_TAKE_THAT_DOES_NOT_EXIST = ScorePayload(gen_id="no-such-take")


def queued_score_job(
    session,
    *,
    payload: ScorePayload | None = A_TAKE_THAT_DOES_NOT_EXIST,
    due_in: float = 0,
) -> Job:
    """A queued score job whose wait ends ``due_in`` seconds from now.

    The default payload names a take that does not exist, so a run of the job ends at once, failed.
    """
    job = create_job(session, JobType.SCORE, payload=payload)
    job.run_after = utcnow() + timedelta(seconds=due_in)
    session.flush()
    return job


@pytest.fixture
def score_queue_wakes() -> Iterator[list[JobQueue]]:
    """The wakes a generation job publishes for the scoring queue, in place of a Redis."""
    woken: list[JobQueue] = []

    async def publish(_channel, queue: JobQueue) -> None:
        woken.append(queue)

    with patch("songmaker_cli.jobs.generation.publish_queue_wake", publish):
        yield woken
