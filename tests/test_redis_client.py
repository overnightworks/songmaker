"""Regression coverage for background lease cleanup."""

import asyncio
import signal

from songmaker_cli.redis_client import _LEASE_RELEASE_TASKS, drain_lease_releases


def test_drain_returns_when_completed_task_discard_callback_is_pending():
    """defect:#1590: shutdown must not spin waiting for scheduled discard callbacks."""
    async def completed_release():
        return None

    async def drain_completed_release():
        task = asyncio.create_task(completed_release())
        await task
        _LEASE_RELEASE_TASKS.add(task)
        task.add_done_callback(_LEASE_RELEASE_TASKS.discard)
        try:
            await drain_lease_releases()
        finally:
            _LEASE_RELEASE_TASKS.discard(task)

    def deadline_expired(signum, frame):
        raise TimeoutError("Lease drain did not return within two seconds")

    # An event-loop timeout cannot interrupt the original non-yielding spin.
    previous_handler = signal.signal(signal.SIGALRM, deadline_expired)
    signal.alarm(2)
    try:
        asyncio.run(drain_completed_release())
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
