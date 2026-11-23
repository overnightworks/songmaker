#!/usr/bin/env python3
"""Lightweight worker health check, without importing the worker module.

Usage: arq_healthcheck.py <queue-name>
  queue-name: "scoring"

The scoring worker is healthy while arq's sentinel key for its queue exists.

Exit codes: 0 = healthy, 1 = unhealthy.
"""
# ruff: noqa: T201 - this health check reports why a worker is unhealthy on stderr

import sys

from pydantic import ValidationError

from songmaker_cli.constants import ARQ_SCORING_HEALTH_KEY
from songmaker_cli.redis_client import RedisConnectionSettings, create_redis

VALID_QUEUES = ("scoring",)


def scoring_is_healthy(redis_url: str) -> bool:
    r = create_redis(redis_url)
    try:
        return r.exists(ARQ_SCORING_HEALTH_KEY) > 0
    finally:
        r.close()


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in VALID_QUEUES:
        print(f"Usage: {sys.argv[0]} <{'|'.join(VALID_QUEUES)}>", file=sys.stderr)
        return 1

    try:
        redis_url = RedisConnectionSettings().redis_url
    except ValidationError:
        print("REDIS_URL is not set", file=sys.stderr)
        return 1

    try:
        healthy = scoring_is_healthy(redis_url)
    except Exception as exc:
        print(f"Redis connection failed: {exc}", file=sys.stderr)
        return 1

    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
