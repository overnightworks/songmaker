"""Redis client utilities — connection, health, rate limiting, metrics, and session cache."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from songmaker_cli.constants import (
    REDIS_METRICS_DURATION_KEY,
    REDIS_METRICS_HTTP_KEY,
    REDIS_METRICS_TOTAL_KEY,
    REDIS_SESSION_PREFIX,
    REDIS_USER_SESSIONS_PREFIX,
)

if TYPE_CHECKING:
    from redis import Redis


def create_redis(url: str) -> Redis:
    from redis import Redis as RedisClient

    return RedisClient.from_url(url, decode_responses=True)


def redis_health(r: Redis) -> bool:
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

    _LUA_SLIDING_WINDOW = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local max_requests = tonumber(ARGV[3])
    redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
    redis.call('ZADD', key, now, tostring(now))
    local count = redis.call('ZCARD', key)
    redis.call('EXPIRE', key, window)
    return count
    """

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        key = f"{self._prefix}:{ip}"
        count = self._redis.eval(self._LUA_SLIDING_WINDOW, 1, key, now, self._window, self._max)
        return count <= self._max


class RedisHttpMetrics:
    """HTTP request metrics backed by Redis hashes."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def record(self, method: str, status_code: int, duration_ms: float) -> None:
        field = f"{method} {status_code}"
        pipe = self._redis.pipeline()
        pipe.hincrby(REDIS_METRICS_HTTP_KEY, field, 1)
        pipe.hincrbyfloat(REDIS_METRICS_DURATION_KEY, "duration_ms", duration_ms)
        pipe.hincrby(REDIS_METRICS_TOTAL_KEY, "total", 1)
        pipe.execute()

    def snapshot(self) -> dict:
        pipe = self._redis.pipeline()
        pipe.hgetall(REDIS_METRICS_HTTP_KEY)
        pipe.hget(REDIS_METRICS_DURATION_KEY, "duration_ms")
        pipe.hget(REDIS_METRICS_TOTAL_KEY, "total")
        counts_raw, duration_raw, total_raw = pipe.execute()

        counts = {k: int(v) for k, v in sorted(counts_raw.items())} if counts_raw else {}
        total = int(total_raw) if total_raw else 0
        duration = float(duration_raw) if duration_raw else 0.0

        return {
            "http_requests_total": counts,
            "http_requests_count": total,
            "http_request_duration_total_ms": round(duration, 1),
        }


class CachedSessionData(BaseModel):
    """Structured session payload stored in Redis."""

    user_id: str
    username: str
    role: str
    is_active: bool
    ip_address: str
    user_agent: str
    expires_at: datetime
    created_at: datetime


class SessionCache:
    """Redis-backed session cache — reduces per-request DB writes."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._failure_lock = threading.Lock()
        self._consecutive_failures: int = 0

    @property
    def consecutive_failures(self) -> int:
        with self._failure_lock:
            return self._consecutive_failures

    def _record_success(self) -> None:
        with self._failure_lock:
            self._consecutive_failures = 0

    def _record_failure(self) -> None:
        with self._failure_lock:
            self._consecutive_failures += 1

    def _session_key(self, session_id: str) -> str:
        return f"{REDIS_SESSION_PREFIX}:{session_id}"

    def _user_sessions_key(self, user_id: str) -> str:
        return f"{REDIS_USER_SESSIONS_PREFIX}:{user_id}"

    def store(
        self,
        session_id: str,
        user_id: str,
        username: str,
        role: str,
        is_active: bool,
        ip_address: str,
        user_agent: str,
        expires_at: datetime,
        created_at: datetime,
        max_age_seconds: int,
    ) -> None:
        data = CachedSessionData(
            user_id=user_id, username=username, role=role, is_active=is_active,
            ip_address=ip_address, user_agent=user_agent,
            expires_at=expires_at, created_at=created_at,
        )
        pipe = self._redis.pipeline()
        pipe.set(self._session_key(session_id), data.model_dump_json(), ex=max_age_seconds)
        pipe.sadd(self._user_sessions_key(user_id), session_id)
        pipe.execute()

    def get(self, session_id: str) -> CachedSessionData | None:
        try:
            raw = self._redis.get(self._session_key(session_id))
        except Exception:
            self._record_failure()
            raise
        self._record_success()
        if raw is None:
            return None
        return CachedSessionData.model_validate_json(raw)

    def refresh_ttl(self, session_id: str, max_age_seconds: int) -> None:
        self._redis.expire(self._session_key(session_id), max_age_seconds)

    _LUA_UPDATE_IP_UA = """
    local key = KEYS[1]
    local ip = ARGV[1]
    local ua = ARGV[2]
    local raw = redis.call('GET', key)
    if not raw then return 0 end
    local ttl = redis.call('TTL', key)
    if ttl <= 0 then return 0 end
    local data = cjson.decode(raw)
    data['ip_address'] = ip
    data['user_agent'] = ua
    redis.call('SET', key, cjson.encode(data), 'EX', ttl)
    return 1
    """

    def update_ip_ua(self, session_id: str, ip_address: str, user_agent: str) -> None:
        key = self._session_key(session_id)
        self._redis.eval(self._LUA_UPDATE_IP_UA, 1, key, ip_address, user_agent)

    def delete(self, session_id: str, user_id: str) -> None:
        pipe = self._redis.pipeline()
        pipe.delete(self._session_key(session_id))
        pipe.srem(self._user_sessions_key(user_id), session_id)
        pipe.execute()

    def delete_user_sessions(self, user_id: str) -> list[str]:
        user_key = self._user_sessions_key(user_id)
        session_ids = list(self._redis.smembers(user_key))
        if session_ids:
            pipe = self._redis.pipeline()
            for sid in session_ids:
                pipe.delete(self._session_key(sid))
            pipe.delete(user_key)
            pipe.execute()
        return session_ids

    def get_all_sessions(self) -> list[tuple[str, int]]:
        prefix = f"{REDIS_SESSION_PREFIX}:"
        all_keys: list[str] = []
        cursor = 0
        while True:
            cursor, keys = self._redis.scan(cursor, match=f"{prefix}*", count=100)
            all_keys.extend(keys)
            if cursor == 0:
                break
        if not all_keys:
            return []
        pipe = self._redis.pipeline()
        for key in all_keys:
            pipe.ttl(key)
        ttls = pipe.execute()
        result = []
        for key, ttl in zip(all_keys, ttls):
            if ttl > 0:
                session_id = key[len(prefix):]
                result.append((session_id, ttl))
        return result
