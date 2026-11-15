"""The owner lease: how a process proves it lives and how another process reads that."""

from __future__ import annotations

import asyncio

import pytest
from support.redis_proxy import redis_proxy
from support.web_app import make_fake_async_redis, settle_owner_leases
from tandem import Liveness

from songmaker_cli.redis_client import create_async_redis
from songmaker_cli.worker_liveness import keep_owner_lease, owner_leases

LEASED = "leased-owner"
ABSENT = "absent-owner"


def test_a_kept_lease_reads_alive_to_another_process_until_its_block_ends() -> None:
    server = make_fake_async_redis()

    async def read_before_during_and_after() -> list[Liveness]:
        await settle_owner_leases(server)
        readings = []
        async with keep_owner_lease(owner_leases(server), LEASED):
            readings.append((await owner_leases(server).liveness([LEASED]))[LEASED])
        readings.append((await owner_leases(server).liveness([LEASED]))[LEASED])
        return readings

    assert asyncio.run(read_before_during_and_after()) == [Liveness.ALIVE, Liveness.GONE]


@pytest.mark.parametrize(
    ("settled", "expected"), [(False, Liveness.UNKNOWN), (True, Liveness.GONE)],
    ids=["a server that may have restarted empty", "a server that has run for the lease span"],
)
def test_an_absent_lease_reads_gone_only_once_the_lease_span_has_passed_on_the_server(
    settled: bool, expected: Liveness,
) -> None:
    server = make_fake_async_redis()

    async def read_the_absent_owner() -> Liveness:
        if settled:
            await settle_owner_leases(server)
        return (await owner_leases(server).liveness([ABSENT]))[ABSENT]

    assert asyncio.run(read_the_absent_owner()) is expected


def test_a_block_that_ends_while_redis_is_unreachable_still_ends(redis_url: str) -> None:
    with redis_proxy(redis_url) as proxy:

        async def cut_redis_inside_the_block() -> None:
            client = create_async_redis(proxy.url)
            try:
                async with keep_owner_lease(owner_leases(client), LEASED):
                    proxy.cut()
            finally:
                await client.aclose()

        asyncio.run(cut_redis_inside_the_block())
