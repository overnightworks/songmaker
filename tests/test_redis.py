"""Tests for Redis client, rate limiter, and metrics."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import fakeredis
import pytest
from conftest import TEST_SECRET
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.auth import hash_password
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import User
from songmaker_cli.redis_client import (
    RedisHttpMetrics,
    RedisRateLimiter,
    create_redis,
    redis_health,
)
from songmaker_cli.server import create_app


@pytest.fixture()
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


# ── create_redis / redis_health ─────────────────────────────────


def test_redis_health_returns_true(fake_redis) -> None:
    assert redis_health(fake_redis) is True


def test_redis_health_returns_false_on_error() -> None:
    broken = MagicMock()
    broken.ping.side_effect = ConnectionError("down")
    assert redis_health(broken) is False


def test_create_redis_returns_client() -> None:
    r = create_redis("redis://localhost:6379/0")
    assert r is not None


# ── RedisRateLimiter ─────────────────────────────────────────────


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
        with patch("songmaker_cli.redis_client.time") as mock_time:
            mock_time.time.return_value = time.time() + 2
            assert limiter.is_allowed("10.0.0.1") is True

    def test_raises_on_redis_failure(self) -> None:
        broken = MagicMock()
        broken.pipeline.return_value.execute.side_effect = ConnectionError("down")
        limiter = RedisRateLimiter(broken, "rl:test", max_requests=10, window_seconds=60)
        with pytest.raises(ConnectionError):
            limiter.is_allowed("10.0.0.1")


# ── RedisHttpMetrics ─────────────────────────────────────────────


class TestRedisHttpMetrics:
    def test_empty_snapshot(self, fake_redis) -> None:
        m = RedisHttpMetrics(fake_redis)
        snap = m.snapshot()
        assert snap["http_requests_count"] == 0
        assert snap["http_request_duration_total_ms"] == 0.0
        assert snap["http_requests_total"] == {}

    def test_record_and_snapshot(self, fake_redis) -> None:
        m = RedisHttpMetrics(fake_redis)
        m.record("GET", 200, 10.0)
        m.record("GET", 200, 20.0)
        m.record("POST", 201, 30.0)
        snap = m.snapshot()
        assert snap["http_requests_count"] == 3
        assert snap["http_request_duration_total_ms"] == 60.0
        assert snap["http_requests_total"]["GET 200"] == 2
        assert snap["http_requests_total"]["POST 201"] == 1


# ── Server integration with Redis ────────────────────────────────


def _make_server_project(tmp_path: Path):
    output_dir = tmp_path / "_output"
    output_dir.mkdir(parents=True)
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Test</html>")
    return output_dir, project_root


def _make_redis_ctx(tmp_path: Path, fake_redis) -> tuple[AppContext, Path, Path]:
    output_dir, project_root = _make_server_project(tmp_path)
    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        session.add(User(
            username="admin", password_hash=hash_password("admin12345"), role="admin",
        ))
        session.commit()
    ctx = AppContext(
        db=factory, output_dir=output_dir, session_secret=TEST_SECRET, redis=fake_redis,
    )
    return ctx, output_dir, project_root


def test_health_reports_redis_ok(tmp_path: Path, fake_redis) -> None:
    ctx, output_dir, project_root = _make_redis_ctx(tmp_path, fake_redis)
    app = create_app(output_dir, project_root, ctx=ctx)
    with TestClient(app) as client:
        resp = client.get("/health")
    data = resp.json()
    assert data["redis"] == "ok"
    assert data["status"] == "ok"


def test_health_reports_redis_error(tmp_path: Path, fake_redis) -> None:
    ctx, output_dir, project_root = _make_redis_ctx(tmp_path, fake_redis)
    app = create_app(output_dir, project_root, ctx=ctx)
    with TestClient(app) as client:
        with patch("songmaker_cli.redis_client.redis_health", return_value=False):
            resp = client.get("/health")
    data = resp.json()
    assert data["redis"] == "error"
    assert data["status"] == "degraded"


def test_health_no_redis_field_when_unconfigured(tmp_path: Path) -> None:
    output_dir, project_root = _make_server_project(tmp_path)
    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        session.add(User(
            username="admin", password_hash=hash_password("admin12345"), role="admin",
        ))
        session.commit()
    ctx = AppContext(db=factory, output_dir=output_dir, session_secret=TEST_SECRET)
    app = create_app(output_dir, project_root, ctx=ctx)
    with TestClient(app) as client:
        resp = client.get("/health")
    assert "redis" not in resp.json()


def test_ip_rate_limit_middleware_uses_redis(tmp_path: Path, fake_redis) -> None:
    ctx, output_dir, project_root = _make_redis_ctx(tmp_path, fake_redis)
    app = create_app(output_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={})
    from conftest import login_and_csrf
    login_and_csrf(client, "admin", "admin12345")
    for _ in range(5):
        resp = client.get("/api/songs")
        assert resp.status_code == 200


def test_redis_rate_limit_503_on_failure(tmp_path: Path) -> None:
    broken_redis = MagicMock()
    broken_redis.ping.return_value = True
    pipe_mock = MagicMock()
    pipe_mock.execute.side_effect = ConnectionError("Redis down")
    broken_redis.pipeline.return_value = pipe_mock

    output_dir, project_root = _make_server_project(tmp_path)
    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        session.add(User(
            username="admin", password_hash=hash_password("admin12345"), role="admin",
        ))
        session.commit()
    ctx = AppContext(
        db=factory, output_dir=output_dir, session_secret=TEST_SECRET, redis=broken_redis,
    )
    app = create_app(output_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={}, raise_server_exceptions=False)
    resp = client.get("/api/songs")
    assert resp.status_code == 503


def test_metrics_with_redis(tmp_path: Path, fake_redis) -> None:
    ctx, output_dir, project_root = _make_redis_ctx(tmp_path, fake_redis)
    app = create_app(output_dir, project_root, ctx=ctx)
    with TestClient(app) as client:
        client.get("/health")
        resp = client.get("/metrics")
    data = resp.json()
    assert "http_requests_total" in data
    assert "http_requests_count" in data
    assert data["http_requests_count"] >= 1


def test_ip_rate_limit_middleware_writes_to_redis(tmp_path: Path, fake_redis) -> None:
    from songmaker_cli.constants import REDIS_RL_IP_PREFIX

    ctx, output_dir, project_root = _make_redis_ctx(tmp_path, fake_redis)
    app = create_app(output_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={})
    from conftest import login_and_csrf
    login_and_csrf(client, "admin", "admin12345")
    client.get("/api/songs")
    keys = [k for k in fake_redis.keys() if k.startswith(REDIS_RL_IP_PREFIX)]
    assert len(keys) > 0
