"""The owner lease: how a process proves it lives and how another process reads that."""

from __future__ import annotations

import asyncio

import pytest
from support.web_app import fake_redis_clock, make_fake_async_redis, settle_owner_leases
from tandem import Liveness

from songmaker_cli.worker_liveness import keep_owner_lease, owner_leases

LEASED = "leased-owner"
ABSENT = "absent-owner"


def test_a_kept_lease_reads_alive_to_another_process_until_its_block_ends(monkeypatch) -> None:
    server = make_fake_async_redis()
    clock = fake_redis_clock(monkeypatch)

    async def read_before_during_and_after() -> list[Liveness]:
        await settle_owner_leases(server, clock)
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
    monkeypatch, settled: bool, expected: Liveness,
) -> None:
    server = make_fake_async_redis()
    clock = fake_redis_clock(monkeypatch)

    async def read_the_absent_owner() -> Liveness:
        if settled:
            await settle_owner_leases(server, clock)
        return (await owner_leases(server).liveness([ABSENT]))[ABSENT]

    assert asyncio.run(read_the_absent_owner()) is expected
