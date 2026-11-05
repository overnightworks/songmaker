#!/usr/bin/env python3
"""Lightweight arq worker health check — checks the Redis sentinel key
without importing the worker module.

Usage: arq_healthcheck.py <queue-name>
  queue-name: "music" or "scoring"

Exit codes: 0 = healthy, 1 = unhealthy.
"""
# ruff: noqa: T201 - this health check reports why a worker is unhealthy on stderr

import sys

from pydantic import ValidationError

from songmaker_cli.redis_client import RedisConnectionSettings, create_redis

HEALTH_KEY_TEMPLATE = "arq:queue:{queue}:health-check"
VALID_QUEUES = ("music", "scoring")


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
    key = HEALTH_KEY_TEMPLATE.format(queue=queue)

    try:
        r = create_redis(redis_url)
        exists = r.exists(key) > 0
        r.close()
    except Exception as exc:
        print(f"Redis connection failed: {exc}", file=sys.stderr)
        return 1

    return 0 if exists else 1


if __name__ == "__main__":
    raise SystemExit(main())
