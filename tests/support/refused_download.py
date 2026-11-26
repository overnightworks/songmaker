"""A download attempt that must not get to run."""

from __future__ import annotations

import fakeredis
import pytest
from support.web_app import SettledFakeAsyncRedis, arrange_fake_async_redis

from songmaker_cli.acestep_state import (
    download_key,
    download_locks,
    single_flight_download,
)


async def attempt_download_that_must_not_run(pool, mode: str, job_id: str) -> None:
    async with single_flight_download(pool, mode, job_id):
        pytest.fail("the download must not run")


def hold_a_download(pool: SettledFakeAsyncRedis, mode: str, job_id: str) -> None:
    """A live download lock of ``mode`` and its label, as a running holder leaves them."""

    async def take_the_lock(holder: fakeredis.FakeAsyncRedis) -> None:
        assert await download_locks(holder).acquire(mode) is not None
        await holder.set(download_key(mode), job_id)

    arrange_fake_async_redis(pool.another_process(), take_the_lock)

