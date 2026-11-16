"""The owner lease: how a process proves it lives and how another process reads that."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from support.redis_proxy import redis_proxy
from support.web_app import make_fake_async_redis, settle_owner_leases
from tandem import Liveness, StoreError

from songmaker_cli.constants import REDIS_KEY_PREFIX
from songmaker_cli.owner_lease_old_key import old_owner_key
from songmaker_cli.redis_client import create_async_redis
from songmaker_cli.worker_liveness import keep_owner_lease, owner_lease_liveness, owner_leases

LEASED = "leased-owner"
ABSENT = "absent-owner"
DEADLINE_SECONDS = 5
FAST_RENEWAL = timedelta(seconds=0.01)


def test_a_kept_lease_reads_alive_to_another_process_until_its_block_ends() -> None:
    server = make_fake_async_redis()

    async def read_before_during_and_after() -> list[Liveness]:
        await settle_owner_leases(server)
        readings = []
        async with keep_owner_lease(owner_leases(server), LEASED):
            readings.append((await owner_lease_liveness(owner_leases(server), [LEASED]))[LEASED])
        readings.append((await owner_lease_liveness(owner_leases(server), [LEASED]))[LEASED])
        return readings

    assert asyncio.run(read_before_during_and_after()) == [Liveness.ALIVE, Liveness.GONE]


def test_an_owner_that_renews_only_the_old_key_reads_alive_until_that_key_lapses() -> None:
    server = make_fake_async_redis()

    async def read_while_the_old_key_is_live_and_after() -> list[Liveness]:
        await settle_owner_leases(server)
        key = old_owner_key(REDIS_KEY_PREFIX, ABSENT)
        await server.set(key, "1")
        readings = [(await owner_lease_liveness(owner_leases(server), [ABSENT]))[ABSENT]]
        await server.delete(key)
        readings.append((await owner_lease_liveness(owner_leases(server), [ABSENT]))[ABSENT])
        return readings

    assert asyncio.run(read_while_the_old_key_is_live_and_after()) == [
        Liveness.ALIVE, Liveness.GONE,
    ]


def test_a_kept_lease_shows_the_old_key_to_an_old_reader_until_its_block_ends() -> None:
    server = make_fake_async_redis()

    async def read_the_old_key_during_and_after() -> list[bool]:
        key = old_owner_key(REDIS_KEY_PREFIX, LEASED)
        async with keep_owner_lease(owner_leases(server), LEASED):
            during = await server.exists(key)
        return [bool(during), bool(await server.exists(key))]

    assert asyncio.run(read_the_old_key_during_and_after()) == [True, False]


def test_a_lease_that_lapsed_and_started_again_counts_as_a_start() -> None:
    server = make_fake_async_redis()

    async def lapse_the_lease_and_wait_for_the_start() -> int:
        starts: list[int] = []
        started = asyncio.Event()

        async def on_new_start() -> None:
            starts.append(1)
            started.set()

        leases = owner_leases(server)
        async with keep_owner_lease(
            leases, LEASED, on_new_start=on_new_start, every=FAST_RENEWAL,
        ) as hold:
            await leases.end(LEASED, hold.generation)
            await asyncio.wait_for(started.wait(), timeout=DEADLINE_SECONDS)
        return len(starts)

    assert asyncio.run(lapse_the_lease_and_wait_for_the_start()) == 1


def test_an_exit_cancelled_during_a_renewal_still_ends_the_lease_and_its_old_key() -> None:
    server = make_fake_async_redis()
    plain_set = server.set
    block_entered = False
    renewal_in_flight = asyncio.Event()
    cancellation_delivered = asyncio.Event()

    async def set_once_the_cancellation_is_delivered(*arguments, **options):
        if block_entered:
            renewal_in_flight.set()
            await cancellation_delivered.wait()
        return await plain_set(*arguments, **options)

    server.set = set_once_the_cancellation_is_delivered

    async def block() -> None:
        nonlocal block_entered
        async with keep_owner_lease(owner_leases(server), LEASED, every=FAST_RENEWAL):
            block_entered = True
            await asyncio.sleep(DEADLINE_SECONDS)

    async def cancel_the_block_twice_while_a_renewal_is_in_flight() -> tuple[Liveness, bool]:
        await settle_owner_leases(server)
        running = asyncio.create_task(block())
        await asyncio.wait_for(renewal_in_flight.wait(), timeout=DEADLINE_SECONDS)
        running.cancel()
        await asyncio.sleep(0)
        running.cancel()
        cancellation_delivered.set()
        await asyncio.gather(running, return_exceptions=True)
        reading = (await owner_lease_liveness(owner_leases(server), [LEASED]))[LEASED]
        return reading, bool(await server.exists(old_owner_key(REDIS_KEY_PREFIX, LEASED)))

    assert asyncio.run(cancel_the_block_twice_while_a_renewal_is_in_flight()) == (
        Liveness.GONE, False,
    )


def test_the_old_key_is_dropped_and_the_error_propagates_when_the_lease_end_raises() -> None:
    server = make_fake_async_redis()
    key = old_owner_key(REDIS_KEY_PREFIX, LEASED)

    async def fail_every_script(*arguments, **options):
        raise RedisConnectionError("the lease script cannot run")

    async def end_the_lease_while_only_scripts_fail() -> tuple[bool, bool]:
        leases = owner_leases(server)
        renewal = await leases.renew(LEASED)
        old_key_before_end = bool(await server.exists(key))
        server.evalsha = fail_every_script
        with pytest.raises(StoreError):
            await leases.end(LEASED, renewal.generation)
        return old_key_before_end, bool(await server.exists(key))

    assert asyncio.run(end_the_lease_while_only_scripts_fail()) == (True, False)


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
        return (await owner_lease_liveness(owner_leases(server), [ABSENT]))[ABSENT]

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
