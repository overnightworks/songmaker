"""A co-writer turn that the shutdown or its client cancels fails its job by what cut it."""

from __future__ import annotations

import asyncio
import time

import pytest

from songmaker_cli.conversation_api import ChatTurnLifecycle, end_running_chat_turns
from songmaker_cli.db.models import Job
from songmaker_cli.health_types import BackgroundLoopRegistry
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.messages import message

JOB_ID = "job-1"


def test_the_turn_drain_returns_at_once_without_running_turns() -> None:
    started = time.monotonic()
    returned = asyncio.run(end_running_chat_turns(60))
    assert (returned, time.monotonic() - started < 1) == (None, True)


@pytest.mark.parametrize(
    ("shutting_down", "failure", "error_type"),
    [
        pytest.param(
            True, message("chatFailure.serverRestarted"), "server_restarted",
            id="a-turn-cancelled-in-the-shutdown-fails-as-a-restart",
        ),
        pytest.param(
            False, message("chatFailure.clientCancelled"), "cancelled",
            id="a-turn-cancelled-by-its-client-fails-as-cancelled",
        ),
    ],
)
def test_a_cancelled_turn_fails_its_job_by_what_cut_it(
    pg_factory, shutting_down: bool, failure, error_type: str,
) -> None:
    registry = BackgroundLoopRegistry()
    if shutting_down:
        registry.begin_shutdown()
    with pg_factory() as session:
        session.add(Job(id=JOB_ID, type=JobType.CHAT, status=JobStatus.RUNNING))
        session.commit()

        async def cancel_the_turn() -> bool:
            heartbeat = asyncio.ensure_future(asyncio.Event().wait())
            await ChatTurnLifecycle(session, JOB_ID, heartbeat, registry).finish(cancelled=True)
            return heartbeat.cancelled()

        heartbeat_stopped = asyncio.run(cancel_the_turn())

    with pg_factory() as session:
        job = session.get(Job, JOB_ID)
        stored = (job.status, job.error_message, job.error_type)

    assert (stored, heartbeat_stopped) == ((JobStatus.FAILED, failure, error_type), True)
