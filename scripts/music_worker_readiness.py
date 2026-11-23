#!/usr/bin/env python3
"""The music worker's readiness probe, without importing the worker module.

The worker is ready once this container start's worker holds a live owner lease: the file it
wrote at its start names the lease and PID 1's start ticks.

Exit codes: 0 = ready, 1 = not ready.
"""
# ruff: noqa: T201 - this probe reports why a worker is not ready on stderr

import asyncio
import sys

from pydantic import ValidationError

from songmaker_cli.constants import MUSIC_WORKER_READINESS_FILE
from songmaker_cli.redis_client import RedisConnectionSettings, create_async_redis
from songmaker_cli.worker_liveness import owner_leases, pid_one_start_ticks, worker_is_ready


async def music_is_ready(redis_url: str) -> bool:
    redis = create_async_redis(redis_url)
    try:
        return await worker_is_ready(
            owner_leases(redis), MUSIC_WORKER_READINESS_FILE, pid_one_start_ticks(),
        )
    finally:
        await redis.aclose()


def main() -> int:
    try:
        redis_url = RedisConnectionSettings().redis_url
    except ValidationError:
        print("REDIS_URL is not set", file=sys.stderr)
        return 1

    try:
        ready = asyncio.run(music_is_ready(redis_url))
    except Exception as exc:
        print(f"Redis connection failed: {exc}", file=sys.stderr)
        return 1

    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
