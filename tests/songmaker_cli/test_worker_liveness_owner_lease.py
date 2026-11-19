"""The owner lease: how a process proves it lives and how another process reads that."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from support.redis_proxy import redis_proxy
from support.web_app import make_fake_async_redis, settle_owner_leases
from tandem import Liveness, StoreError

from songmaker_cli.redis_client import create_async_redis
from songmaker_cli.worker_liveness import (
    JobOwnerStamp,
    keep_owner_lease,
    owner_lease_liveness,
    owner_leases,
)

LEASED = "leased-owner"
ABSENT = "absent-owner"
DEADLINE_SECONDS = 5
FAST_RENEWAL = timedelta(seconds=0.01)


async def _liveness_of(server, owner_id: str, generation: str | None = None) -> Liveness:
    stamp = JobOwnerStamp(owner_id, generation)
    return (await owner_lease_liveness(owner_leases(server), [stamp]))[stamp]


def test_a_kept_lease_reads_alive_to_another_process_until_its_block_ends() -> None:
    server = make_fake_async_redis()

    async def read_before_during_and_after() -> list[Liveness]:
        await settle_owner_leases(server)
        readings = []
        async with keep_owner_lease(owner_leases(server), LEASED):
            readings.append(await _liveness_of(server, LEASED))
        readings.append(await _liveness_of(server, LEASED))
        return readings

    assert asyncio.run(read_before_during_and_after()) == [Liveness.ALIVE, Liveness.GONE]


def test_a_stamp_of_a_lapsed_generation_reads_gone_while_its_owner_lives_on() -> None:
    server = make_fake_async_redis()

    async def read_the_stamps_after_the_lease_started_anew() -> list[Liveness]:
        await settle_owner_leases(server)
        leases = owner_leases(server)
        async with keep_owner_lease(leases, LEASED) as owner:
            lapsed = owner.generation
            await leases.end(LEASED, lapsed)
            started_anew = (await leases.renew(LEASED)).generation
            return [
                await _liveness_of(server, LEASED, lapsed),
                await _liveness_of(server, LEASED, started_anew),
                await _liveness_of(server, LEASED),
            ]

    assert asyncio.run(read_the_stamps_after_the_lease_started_anew()) == [
        Liveness.GONE, Liveness.ALIVE, Liveness.ALIVE,
    ]


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
        ) as owner:
            await leases.end(LEASED, owner.generation)
            await asyncio.wait_for(started.wait(), timeout=DEADLINE_SECONDS)
        return len(starts)

    assert asyncio.run(lapse_the_lease_and_wait_for_the_start()) == 1


def test_an_exit_cancelled_during_a_renewal_still_ends_the_lease() -> None:
    server = make_fake_async_redis()
    plain_evalsha = server.evalsha
    block_entered = False
    renewal_in_flight = asyncio.Event()
    cancellation_delivered = asyncio.Event()

    async def run_once_the_cancellation_is_delivered(*arguments, **options):
        if block_entered:
            renewal_in_flight.set()
            await cancellation_delivered.wait()
        return await plain_evalsha(*arguments, **options)

    server.evalsha = run_once_the_cancellation_is_delivered

    async def block() -> None:
        nonlocal block_entered
        async with keep_owner_lease(owner_leases(server), LEASED, every=FAST_RENEWAL):
            block_entered = True
            await asyncio.sleep(DEADLINE_SECONDS)

    async def cancel_the_block_twice_while_a_renewal_is_in_flight() -> Liveness:
        await settle_owner_leases(server)
        running = asyncio.create_task(block())
        await asyncio.wait_for(renewal_in_flight.wait(), timeout=DEADLINE_SECONDS)
        running.cancel()
        await asyncio.sleep(0)
        running.cancel()
        cancellation_delivered.set()
        await asyncio.gather(running, return_exceptions=True)
        return await _liveness_of(server, LEASED)

    assert asyncio.run(cancel_the_block_twice_while_a_renewal_is_in_flight()) == Liveness.GONE


def test_the_error_propagates_when_the_lease_end_raises() -> None:
    server = make_fake_async_redis()

    async def fail_every_script(*arguments, **options):
        raise RedisConnectionError("the lease script cannot run")

    async def end_the_lease_while_only_scripts_fail() -> None:
        leases = owner_leases(server)
        renewal = await leases.renew(LEASED)
        server.evalsha = fail_every_script
        with pytest.raises(StoreError):
            await leases.end(LEASED, renewal.generation)

    asyncio.run(end_the_lease_while_only_scripts_fail())


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
        return await _liveness_of(server, ABSENT)

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
