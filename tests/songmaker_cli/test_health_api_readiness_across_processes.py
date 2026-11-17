"""A web process is Ready when it can serve, never because it holds a scarce resource."""

from __future__ import annotations

import httpx
import pytest
from redis import Redis
from support.app_processes import HEALTH_PATH, WebProcess, leased_owner_ids, poll_until
from support.web_cluster_world import start_owner

REQUEST_TIMEOUT_SECONDS = 10.0
READINESS_DEADLINE_SECONDS = 20.0


@pytest.fixture
def redis_client(redis_url: str):
    with Redis.from_url(redis_url, decode_responses=True) as client:
        yield client


def _health_status(web_process: WebProcess) -> int:
    return httpx.get(
        f"{web_process.url}{HEALTH_PATH}", timeout=REQUEST_TIMEOUT_SECONDS,
    ).status_code


def test_a_second_process_turns_ready_while_the_first_holds_its_lease(
    web_cluster, redis_client,
) -> None:
    cluster, _ = web_cluster
    process_a, owner_a = start_owner(cluster, redis_client, "a")

    process_b = cluster.start("b")

    assert (
        _health_status(process_a),
        _health_status(process_b),
        owner_a in leased_owner_ids(redis_client),
    ) == (200, 200, True)


def test_every_process_reports_not_ready_while_redis_is_unreachable_and_ready_again_after(
    proxied_cluster,
) -> None:
    cluster, _, proxy = proxied_cluster
    processes = [cluster.start("a"), cluster.start("b")]

    proxy.cut()
    while_down = [
        poll_until(
            lambda each=each: _health_status(each) == 503,
            deadline_seconds=READINESS_DEADLINE_SECONDS,
        )
        for each in processes
    ]
    proxy.restore()
    after = [
        poll_until(
            lambda each=each: _health_status(each) == 200,
            deadline_seconds=READINESS_DEADLINE_SECONDS,
        )
        for each in processes
    ]

    assert (while_down, after) == ([True, True], [True, True])
