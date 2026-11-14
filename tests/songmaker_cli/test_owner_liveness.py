"""The owner lease: how a process proves it lives and how another process reads that."""

from __future__ import annotations

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from songmaker_cli.job_timing import OWNER_LEASE_TTL_SECONDS
from songmaker_cli.worker_liveness import (
    WorkerLiveness,
    drop_owner_lease,
    owner_lease_key,
    read_owner_liveness,
    refresh_owner_lease,
)

LEASED = "leased-owner"
ABSENT = "absent-owner"


class _Server:
    """The two Redis calls the reader makes, answered like a server with these keys and age."""

    def __init__(self, *, keys: set[str], uptime_seconds: int | None = None) -> None:
        self.keys = keys
        self.uptime_seconds = uptime_seconds

    def mget(self, keys: list[str]) -> list[str | None]:
        return ["1" if key in self.keys else None for key in keys]

    def info(self, section: str) -> dict[str, int]:
        assert section == "server"
        return {"uptime_in_seconds": self.uptime_seconds}


@pytest.mark.parametrize(
    ("uptime_seconds", "expected_for_absent"),
    [
        (OWNER_LEASE_TTL_SECONDS - 1, WorkerLiveness.UNKNOWN),
        (OWNER_LEASE_TTL_SECONDS, WorkerLiveness.DEAD),
    ],
)
def test_an_absent_lease_is_dead_only_once_the_server_has_run_for_the_lease_ttl(
    uptime_seconds: int, expected_for_absent: WorkerLiveness,
) -> None:
    server = _Server(keys={owner_lease_key(LEASED)}, uptime_seconds=uptime_seconds)

    assert read_owner_liveness(server, [LEASED, ABSENT]) == {
        LEASED: WorkerLiveness.ALIVE,
        ABSENT: expected_for_absent,
    }


def test_a_server_that_cannot_be_read_raises_so_that_the_caller_sees_the_failure() -> None:
    class Unreachable:
        def mget(self, keys):
            raise RedisConnectionError("down")

    with pytest.raises(RedisConnectionError):
        read_owner_liveness(Unreachable(), [LEASED])


def test_no_owner_to_read_asks_the_server_nothing() -> None:
    class Untouched:
        def __getattr__(self, name):
            raise AssertionError(f"read {name}")

    assert read_owner_liveness(Untouched(), []) == {}


def test_a_refreshed_lease_reads_alive_and_a_dropped_one_does_not(redis_url: str) -> None:
    from redis import Redis

    with Redis.from_url(redis_url, decode_responses=True) as server:
        refresh_owner_lease(server, LEASED)
        assert server.ttl(owner_lease_key(LEASED)) in range(1, OWNER_LEASE_TTL_SECONDS + 1)
        assert read_owner_liveness(server, [LEASED])[LEASED] is WorkerLiveness.ALIVE

        drop_owner_lease(server, LEASED)
        assert server.exists(owner_lease_key(LEASED)) == 0
