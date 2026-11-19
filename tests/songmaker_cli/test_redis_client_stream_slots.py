"""The stream caps count in a real Redis: refused at the cap, admitted again after a release."""

import asyncio
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from anyio import to_thread
from fastapi import HTTPException

from songmaker_cli import jobs_api, resource_event_api
from songmaker_cli.redis_client import create_async_redis
from songmaker_cli.settings import get_settings

JOB_STREAM_PER_PERSON_CAP = 2
JOB_STREAM_GLOBAL_CAP = 3


class _AlwaysOpen:
    def is_allowed(self, _user_id: str, *, limit: int, window_seconds: int) -> bool:
        return True


@pytest.fixture(params=["job-stream", "resource-stream"])
def stream_family(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, fresh_settings: None,
) -> tuple[Callable, int, int]:
    """The family's endpoint-side take with its per-person and global cap.

    The job streams' caps come in through configuration; the resource streams run
    with the caps their module declares.
    """
    if request.param == "job-stream":
        monkeypatch.setenv("JOB_STREAM_LEASE_MAX_PER_USER", str(JOB_STREAM_PER_PERSON_CAP))
        monkeypatch.setenv("JOB_STREAM_LEASE_MAX_GLOBAL", str(JOB_STREAM_GLOBAL_CAP))
        get_settings.cache_clear()
        return jobs_api._take_job_stream_slot, JOB_STREAM_PER_PERSON_CAP, JOB_STREAM_GLOBAL_CAP
    return (
        resource_event_api._take_stream_slot,
        resource_event_api.RESOURCE_EVENT_STREAM_MAX_PER_USER,
        resource_event_api.RESOURCE_EVENT_STREAM_MAX_GLOBAL,
    )


def test_streams_are_capped_per_person_and_globally_and_a_release_admits_again(
    stream_family: tuple[Callable, int, int], redis_url: str,
) -> None:
    take_slot, per_person_cap, global_cap = stream_family

    async def scenario() -> None:
        async_redis = create_async_redis(redis_url)
        state = SimpleNamespace(
            ctx=SimpleNamespace(async_redis=async_redis),
            _resource_stream_open_limiter=_AlwaysOpen(),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=state))

        async def take(person: str) -> tuple:
            return await to_thread.run_sync(take_slot, request, person)

        async def refused(person: str) -> int:
            with pytest.raises(HTTPException) as refusal:
                await take(person)
            return refusal.value.status_code

        try:
            alice_slots, alice_token = await take("alice")
            for _ in range(per_person_cap - 1):
                await take("alice")
            assert await refused("alice") == 429
            for _ in range(global_cap - per_person_cap):
                await take("bob")
            assert await refused("carol") == 429
            assert await alice_slots.release(alice_token)
            await take("carol")
        finally:
            await async_redis.aclose()

    asyncio.run(asyncio.wait_for(scenario(), timeout=20))
