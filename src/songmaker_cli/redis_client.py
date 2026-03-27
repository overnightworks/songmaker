"""Redis client utilities — connection, health, rate limiting, and metrics."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis import Redis

log = logging.getLogger(__name__)

REDIS_KEY_PREFIX = "songmaker"


def create_redis(url: str) -> Redis:
    """Create a Redis client with connection pooling from a URL."""
    from redis import Redis as RedisClient

    return RedisClient.from_url(url, decode_responses=True)


def redis_health(r: Redis) -> bool:
    """Check Redis connectivity via PING."""
    try:
        return r.ping()
    except Exception:
        return False


class RedisRateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets."""

    def __init__(
        self, redis: Redis, prefix: str, max_requests: int, window_seconds: int,
    ) -> None:
        self._redis = redis
        self._prefix = prefix
        self._max = max_requests
        self._window = window_seconds

    def is_allowed(self, ip: str) -> bool:
        """Check if a request from this IP is within the rate limit.

        Raises on Redis failure — callers must handle (fail-closed).
        """
        now = time.time()
        key = f"{self._prefix}:{ip}"
        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - self._window)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, self._window)
        results = pipe.execute()
        return results[2] <= self._max


class RedisHttpMetrics:
    """HTTP request metrics backed by Redis hashes."""

    _COUNTS_KEY = f"{REDIS_KEY_PREFIX}:metrics:http"
    _DURATION_KEY = f"{REDIS_KEY_PREFIX}:metrics:http:duration"
    _TOTAL_KEY = f"{REDIS_KEY_PREFIX}:metrics:http:total"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def record(self, method: str, status_code: int, duration_ms: float) -> None:
        field = f"{method} {status_code}"
        pipe = self._redis.pipeline()
        pipe.hincrby(self._COUNTS_KEY, field, 1)
        pipe.hincrbyfloat(self._DURATION_KEY, "duration_ms", duration_ms)
        pipe.hincrby(self._TOTAL_KEY, "total", 1)
        pipe.execute()

    def snapshot(self) -> dict:
        pipe = self._redis.pipeline()
        pipe.hgetall(self._COUNTS_KEY)
        pipe.hget(self._DURATION_KEY, "duration_ms")
        pipe.hget(self._TOTAL_KEY, "total")
        counts_raw, duration_raw, total_raw = pipe.execute()

        counts = {k: int(v) for k, v in sorted(counts_raw.items())} if counts_raw else {}
        total = int(total_raw) if total_raw else 0
        duration = float(duration_raw) if duration_raw else 0.0

        return {
            "http_requests_total": counts,
            "http_requests_count": total,
            "http_request_duration_total_ms": round(duration, 1),
        }
