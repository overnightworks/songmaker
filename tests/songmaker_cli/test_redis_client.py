"""Regression coverage for the background release of stream slots."""

import asyncio
import signal

import pytest

from songmaker_cli.redis_client import SlotReleases


def test_drain_returns_when_a_finished_release_discard_callback_is_pending():
    """defect:#1590: shutdown must not spin waiting for scheduled discard callbacks."""
    class _Slots:
        async def release(self, _token: str) -> bool:
            return True

    async def drain_finished_release():
        releases = SlotReleases()
        releases.release_in_background(_Slots(), "token", subject="Test stream")
        await asyncio.sleep(0)
        await releases.drain()

    def deadline_expired(signum, frame):
        raise TimeoutError("Slot drain did not return within two seconds")

    # An event-loop timeout cannot interrupt the original non-yielding spin.
    previous_handler = signal.signal(signal.SIGALRM, deadline_expired)
    signal.alarm(2)
    try:
        asyncio.run(drain_finished_release())
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


@pytest.mark.parametrize("outcome", [False, ConnectionError("redis unavailable")])
def test_a_release_that_returns_false_or_raises_is_logged_and_harms_nothing(
    outcome: bool | Exception, caplog: pytest.LogCaptureFixture,
) -> None:
    class _Slots:
        async def release(self, _token: str) -> bool:
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    async def release_and_drain() -> None:
        releases = SlotReleases()
        releases.release_in_background(_Slots(), "secret-token", subject="Test stream")
        await releases.drain()

    with caplog.at_level("WARNING", logger="songmaker_cli.redis_client"):
        asyncio.run(release_and_drain())

    assert "Test stream" in caplog.text
    assert "secret-token" not in caplog.text
