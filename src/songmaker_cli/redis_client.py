"""Redis client utilities — connection, health, rate limiting, metrics, and session cache."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import TYPE_CHECKING

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

    def is_allowed(self, ip: str) -> bool:
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


class SessionCache:
    """Redis-backed session cache — reduces per-request DB writes."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._consecutive_failures: int = 0

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def _record_success(self) -> None:
        self._consecutive_failures = 0

    def _record_failure(self) -> None:
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
        payload = json.dumps({
            "user_id": user_id,
            "username": username,
            "role": role,
            "is_active": is_active,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "expires_at": expires_at.isoformat(),
            "created_at": created_at.isoformat(),
        })
        pipe = self._redis.pipeline()
        pipe.set(self._session_key(session_id), payload, ex=max_age_seconds)
        pipe.sadd(self._user_sessions_key(user_id), session_id)
        pipe.execute()

    def get(self, session_id: str) -> dict | None:
        try:
            raw = self._redis.get(self._session_key(session_id))
        except Exception:
            self._record_failure()
            raise
        self._record_success()
        if raw is None:
            return None
        data = json.loads(raw)
        data["expires_at"] = datetime.fromisoformat(data["expires_at"])
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        return data

    def refresh_ttl(self, session_id: str, max_age_seconds: int) -> None:
        self._redis.expire(self._session_key(session_id), max_age_seconds)

    def update_ip_ua(self, session_id: str, ip_address: str, user_agent: str) -> None:
        key = self._session_key(session_id)
        raw = self._redis.get(key)
        if raw is None:
            return
        data = json.loads(raw)
        data["ip_address"] = ip_address
        data["user_agent"] = user_agent
        ttl = self._redis.ttl(key)
        if ttl > 0:
            self._redis.set(key, json.dumps(data), ex=ttl)

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
        result = []
        cursor = 0
        while True:
            cursor, keys = self._redis.scan(cursor, match=f"{prefix}*", count=100)
            for key in keys:
                session_id = key[len(prefix):]
                ttl = self._redis.ttl(key)
                if ttl > 0:
                    result.append((session_id, ttl))
            if cursor == 0:
                break
        return result
