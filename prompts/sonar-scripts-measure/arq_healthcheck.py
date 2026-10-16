#!/usr/bin/env python3
"""Lightweight arq worker health check — checks the Redis sentinel key
without importing the worker module.

Usage: arq_healthcheck.py <queue-name>
  queue-name: "music" or "scoring"

Exit codes: 0 = healthy, 1 = unhealthy.
"""

import os
import sys

from redis import Redis

HEALTH_KEY_TEMPLATE = "arq:queue:{queue}:health-check"
VALID_QUEUES = ("music", "scoring")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in VALID_QUEUES:
        print(f"Usage: {sys.argv[0]} <{'|'.join(VALID_QUEUES)}>", file=sys.stderr)
        return 1

    queue = sys.argv[1]
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    key = HEALTH_KEY_TEMPLATE.format(queue=queue)

    try:
        r = Redis.from_url(redis_url)
        exists = r.exists(key) > 0
        r.close()
    except Exception as exc:
        print(f"Redis connection failed: {exc}", file=sys.stderr)
        return 1

    return 0 if exists else 1


if __name__ == "__main__":
    raise SystemExit(main())
