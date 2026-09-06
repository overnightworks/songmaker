"""The sliding-window limiter: what it lets through and what it blocks."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

from webauth.rate_limit import RedisRateLimiter


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


class TestRedisRateLimiter:
    def test_allows_within_limit(self, fake_redis) -> None:
        limiter = RedisRateLimiter(fake_redis, "rl:test", max_requests=3, window_seconds=60)
        assert limiter.is_allowed("10.0.0.1") is True
        assert limiter.is_allowed("10.0.0.1") is True
        assert limiter.is_allowed("10.0.0.1") is True

    def test_blocks_over_limit(self, fake_redis) -> None:
        limiter = RedisRateLimiter(fake_redis, "rl:test", max_requests=2, window_seconds=60)
        limiter.is_allowed("10.0.0.1")
        limiter.is_allowed("10.0.0.1")
        assert limiter.is_allowed("10.0.0.1") is False

    def test_counts_requests_with_identical_timestamps(self, fake_redis) -> None:
        limiter = RedisRateLimiter(fake_redis, "rl:test", max_requests=2, window_seconds=60)
        with patch("webauth.rate_limit.time.time", return_value=1234.5):
            assert limiter.is_allowed("10.0.0.1") is True
            assert limiter.is_allowed("10.0.0.1") is True
            assert limiter.is_allowed("10.0.0.1") is False
            for _ in range(1_000):
                assert limiter.is_allowed("10.0.0.1") is False
            assert fake_redis.zcard("rl:test:10.0.0.1") == 2

    def test_different_ips_independent(self, fake_redis) -> None:
        limiter = RedisRateLimiter(fake_redis, "rl:test", max_requests=1, window_seconds=60)
        assert limiter.is_allowed("10.0.0.1") is True
        assert limiter.is_allowed("10.0.0.2") is True
        assert limiter.is_allowed("10.0.0.1") is False

    def test_different_prefixes_independent(self, fake_redis) -> None:
        limiter_a = RedisRateLimiter(fake_redis, "rl:a", max_requests=1, window_seconds=60)
        limiter_b = RedisRateLimiter(fake_redis, "rl:b", max_requests=1, window_seconds=60)
        assert limiter_a.is_allowed("10.0.0.1") is True
        assert limiter_b.is_allowed("10.0.0.1") is True
        assert limiter_a.is_allowed("10.0.0.1") is False
        assert limiter_b.is_allowed("10.0.0.1") is False

    def test_window_expiry(self, fake_redis) -> None:
        limiter = RedisRateLimiter(fake_redis, "rl:test", max_requests=1, window_seconds=1)
        assert limiter.is_allowed("10.0.0.1") is True
        assert limiter.is_allowed("10.0.0.1") is False
        with patch("webauth.rate_limit.time") as mock_time:
            mock_time.time.return_value = time.time() + 2
            assert limiter.is_allowed("10.0.0.1") is True

    def test_raises_on_redis_failure(self) -> None:
        broken = MagicMock()
        broken.eval.side_effect = ConnectionError("down")
        limiter = RedisRateLimiter(broken, "rl:test", max_requests=10, window_seconds=60)
        with pytest.raises(ConnectionError):
            limiter.is_allowed("10.0.0.1")
