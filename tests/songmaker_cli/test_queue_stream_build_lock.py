"""The queue-stream build lock keeps a build exclusive for longer than the lock lasts."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Lock
from types import SimpleNamespace

import anyio
import pytest
from anyio.from_thread import start_blocking_portal
from support.web_app import SettledFakeAsyncRedis

from songmaker_cli.queue_stream_build_lock import (
    FAILED_RENEWAL_WARNING,
    LOST_LOCK_WARNING,
    build_lock,
)

SHORT_LOCK_LASTS = timedelta(seconds=0.4)
BUILD_SECONDS = 3 * SHORT_LOCK_LASTS.total_seconds()
KEY = "content-hash"


def test_a_build_longer_than_the_lock_lasts_stays_exclusive() -> None:
    ctx = SimpleNamespace(async_redis=SettledFakeAsyncRedis())
    builders_inside: list[int] = []
    inside = 0
    guard = Lock()

    def build() -> None:
        nonlocal inside
        with build_lock(ctx, KEY, lasts=SHORT_LOCK_LASTS):
            with guard:
                inside += 1
                builders_inside.append(inside)
            time.sleep(BUILD_SECONDS)
            with guard:
                inside -= 1

    def build_in_a_request_thread(portal) -> None:
        portal.call(anyio.to_thread.run_sync, build)

    with start_blocking_portal() as portal, ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(build_in_a_request_thread, portal) for _ in range(2)]:
            future.result()

    assert builders_inside == [1, 1]


async def _lock_lost(self, name: str, generation: str) -> bool:
    return False


async def _redis_unreachable(self, name: str, generation: str) -> bool:
    raise ConnectionError


@pytest.mark.parametrize(
    ("extension", "warning"),
    [(_lock_lost, LOST_LOCK_WARNING), (_redis_unreachable, FAILED_RENEWAL_WARNING)],
    ids=["lock-lost", "redis-error"],
)
def test_a_lock_that_cannot_be_renewed_is_logged_and_the_build_finishes(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, extension, warning: str,
) -> None:
    monkeypatch.setattr("tandem.Locks.extend", extension)
    ctx = SimpleNamespace(async_redis=SettledFakeAsyncRedis())

    def build() -> None:
        with build_lock(ctx, KEY, lasts=SHORT_LOCK_LASTS):
            time.sleep(SHORT_LOCK_LASTS.total_seconds())

    with caplog.at_level(logging.WARNING), start_blocking_portal() as portal:
        portal.call(anyio.to_thread.run_sync, build)

    assert warning in caplog.text
