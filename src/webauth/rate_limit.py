"""The sliding-window counter every per-address budget is measured with.

One Redis sorted set per key holds the timestamps inside the current window;
the window slides on every check, so a caller regains budget continuously
rather than at a fixed reset. The whole check is one Lua script so that
trimming, counting, and recording cannot interleave with another request.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis import Redis


class RedisRateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets."""

    def __init__(
        self, redis: Redis, prefix: str, max_requests: int, window_seconds: int,
    ) -> None:
        self._redis = redis
        self._prefix = prefix
        self._max = max_requests
        self._window = window_seconds

    _LUA_SLIDING_WINDOW = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local max_requests = tonumber(ARGV[3])
    local member = ARGV[4]
    redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
    local count = redis.call('ZCARD', key)
    if count >= max_requests then return count + 1 end
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, window)
    return count + 1
    """

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        key = f"{self._prefix}:{ip}"
        count = self._redis.eval(
            self._LUA_SLIDING_WINDOW,
            1,
            key,
            now,
            self._window,
            self._max,
            uuid.uuid4().hex,
        )
        return count <= self._max
