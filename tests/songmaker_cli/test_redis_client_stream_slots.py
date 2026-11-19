"""The stream caps count in a real Redis: refused at the cap, admitted again after a release."""

import asyncio
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from anyio import to_thread
from fastapi import HTTPException

from songmaker_cli import jobs_api, resource_event_api
from songmaker_cli.redis_client import create_async_redis

PER_PERSON_CAP = 2
GLOBAL_CAP = 3


class _AlwaysOpen:
    def is_allowed(self, _user_id: str, *, limit: int, window_seconds: int) -> bool:
        return True


@pytest.fixture(params=["job-stream", "resource-stream"])
def take_slot(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Callable:
    """The family's endpoint-side take, with the family's caps set to the two cap constants."""
    settings = SimpleNamespace(
        job_stream_lease_max_per_user=PER_PERSON_CAP,
        job_stream_lease_max_global=GLOBAL_CAP,
        database_pool_size=10,
        database_max_overflow=5,
        resource_event_stream_open_limit=100,
    )
    monkeypatch.setattr(jobs_api, "get_settings", lambda: settings)
    monkeypatch.setattr(resource_event_api, "get_settings", lambda: settings)
    monkeypatch.setattr(resource_event_api, "RESOURCE_EVENT_STREAM_MAX_PER_USER", PER_PERSON_CAP)
    monkeypatch.setattr(resource_event_api, "RESOURCE_EVENT_STREAM_MAX_GLOBAL", GLOBAL_CAP)
    if request.param == "job-stream":
        return jobs_api._take_job_stream_slot
    return resource_event_api._take_stream_slot


def test_streams_are_capped_per_person_and_globally_and_a_release_admits_again(
    take_slot: Callable, redis_url: str,
) -> None:
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
            await take("alice")
            assert await refused("alice") == 429
            await take("bob")
            assert await refused("carol") == 429
            assert await alice_slots.release(alice_token)
            await take("carol")
        finally:
            await async_redis.aclose()

    asyncio.run(asyncio.wait_for(scenario(), timeout=20))
