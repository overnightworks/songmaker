#!/usr/bin/env python3
"""Lightweight worker health check, without importing the worker module.

Usage: arq_healthcheck.py <queue-name>
  queue-name: "music" or "scoring"

The scoring worker is healthy while arq's sentinel key for its queue exists. The music worker is
ready once this container start's worker holds a live owner lease: the file it wrote at its
start names the lease and PID 1's start ticks.

Exit codes: 0 = healthy, 1 = unhealthy.
"""
# ruff: noqa: T201 - this health check reports why a worker is unhealthy on stderr

import asyncio
import sys

from pydantic import ValidationError

from songmaker_cli.constants import ARQ_SCORING_HEALTH_KEY, MUSIC_WORKER_READINESS_FILE
from songmaker_cli.redis_client import RedisConnectionSettings, create_async_redis, create_redis
from songmaker_cli.worker_liveness import owner_leases, pid_one_start_ticks, worker_is_ready

VALID_QUEUES = ("music", "scoring")


def scoring_is_healthy(redis_url: str) -> bool:
    r = create_redis(redis_url)
    try:
        return r.exists(ARQ_SCORING_HEALTH_KEY) > 0
    finally:
        r.close()


async def music_is_ready(redis_url: str) -> bool:
    redis = create_async_redis(redis_url)
    try:
        return await worker_is_ready(
            owner_leases(redis), MUSIC_WORKER_READINESS_FILE, pid_one_start_ticks(),
        )
    finally:
        await redis.aclose()


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in VALID_QUEUES:
        print(f"Usage: {sys.argv[0]} <{'|'.join(VALID_QUEUES)}>", file=sys.stderr)
        return 1

    queue = sys.argv[1]
    try:
        redis_url = RedisConnectionSettings().redis_url
    except ValidationError:
        print("REDIS_URL is not set", file=sys.stderr)
        return 1

    try:
        if queue == "music":
            healthy = asyncio.run(music_is_ready(redis_url))
        else:
            healthy = scoring_is_healthy(redis_url)
    except Exception as exc:
        print(f"Redis connection failed: {exc}", file=sys.stderr)
        return 1

    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
