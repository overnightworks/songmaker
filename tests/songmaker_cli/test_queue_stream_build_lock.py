"""The queue-stream build lock keeps a build exclusive for longer than the lock lasts."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Lock
from types import SimpleNamespace

import anyio
from anyio.from_thread import start_blocking_portal
from support.web_app import SettledFakeAsyncRedis

from songmaker_cli.queue_stream_build_lock import build_lock

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
