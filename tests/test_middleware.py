"""Tests for session auth dependency and FastAPI integration."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from songmaker_cli.auth import get_client_ip, hash_password, sign_session_id
from songmaker_cli.db.engine import get_db_session, init_db, reset_engine
from songmaker_cli.db.queries import create_session, create_user
from songmaker_cli.middleware import (
    SESSION_COOKIE,
    AuthenticatedUser,
    get_current_user,
    require_admin,
)


@pytest.fixture()
def _db(tmp_path: Path):
    reset_engine()
    init_db(tmp_path / "test.db")
    yield
    reset_engine()


@pytest.fixture()
def auth_app(_db) -> TestClient:
    """Minimal FastAPI app with auth dependency — no middleware stack."""
    app = FastAPI()

    @app.get("/protected")
    def protected(
        request: Request,
        user: AuthenticatedUser = Depends(get_current_user),
        db: Session = Depends(get_db_session),
    ):
        db.commit()
        return {
            "username": user.username,
            "role": user.role,
            "session_id_set": hasattr(request.state, "session_id"),
        }

    @app.get("/admin-only")
    def admin_only(user: AuthenticatedUser = Depends(require_admin)):
        return {"username": user.username}

    @app.get("/public")
    def public():
        return {"status": "ok"}

    return TestClient(app, cookies={})


def _create_user_and_session(
    role: str = "user", active: bool = True, expired: bool = False,
    created_days_ago: int = 0,
) -> str:
    from songmaker_cli.db.engine import get_session_factory

    factory = get_session_factory()
    with factory() as session:
        user = create_user(
            session, f"test_{role}_{active}_{expired}_{created_days_ago}",
            hash_password("t3stP@ssw0rd"), role=role,
        )
        user.is_active = active
        session.flush()
        if expired:
            expires = datetime.now(timezone.utc) - timedelta(days=1)
        else:
            expires = datetime.now(timezone.utc) + timedelta(days=30)
        user_session = create_session(session, user.id, expires)
        if created_days_ago:
            user_session.created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
        session.commit()
        return user_session.id


# ── No cookie / bad cookie ────────────────────────────────────────


def test_no_cookie_returns_401(auth_app: TestClient) -> None:
    resp = auth_app.get("/protected")
    assert resp.status_code == 401


def test_unsigned_cookie_returns_401(auth_app: TestClient) -> None:
    auth_app.cookies.set(SESSION_COOKIE, "raw-no-hmac")
    resp = auth_app.get("/protected")
    assert resp.status_code == 401


def test_nonexistent_session_returns_401(auth_app: TestClient) -> None:
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id("nonexistent"))
    resp = auth_app.get("/protected")
    assert resp.status_code == 401


# ── Expiry ────────────────────────────────────────────────────────


def test_expired_session_returns_401(auth_app: TestClient) -> None:
    sid = _create_user_and_session(expired=True)
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid))
    resp = auth_app.get("/protected")
    assert resp.status_code == 401


def test_absolute_max_age_expired(auth_app: TestClient) -> None:
    sid = _create_user_and_session(created_days_ago=91)
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid))
    resp = auth_app.get("/protected")
    assert resp.status_code == 401


# ── Disabled user ─────────────────────────────────────────────────


def test_disabled_user_returns_403(auth_app: TestClient) -> None:
    sid = _create_user_and_session(active=False)
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid))
    resp = auth_app.get("/protected")
    assert resp.status_code == 403


# ── Valid session ─────────────────────────────────────────────────


def test_valid_session_returns_200(auth_app: TestClient) -> None:
    sid = _create_user_and_session()
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid))
    resp = auth_app.get("/protected")
    assert resp.status_code == 200
    assert resp.json()["username"].startswith("test_user")


def test_session_id_set_on_request_state(auth_app: TestClient) -> None:
    sid = _create_user_and_session()
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid))
    resp = auth_app.get("/protected")
    assert resp.status_code == 200
    assert resp.json()["session_id_set"] is True


def test_sliding_window_renewal(auth_app: TestClient) -> None:
    from songmaker_cli.db.engine import get_session_factory
    from songmaker_cli.db.queries import get_session_with_user

    sid = _create_user_and_session()
    factory = get_session_factory()

    with factory() as db:
        old_expires = get_session_with_user(db, sid).expires_at

    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid))
    auth_app.get("/protected")

    with factory() as db:
        new_expires = get_session_with_user(db, sid).expires_at
        assert new_expires >= old_expires


def test_public_route_no_auth_needed(auth_app: TestClient) -> None:
    resp = auth_app.get("/public")
    assert resp.status_code == 200


# ── Admin dependency ──────────────────────────────────────────────


def test_require_admin_rejects_regular_user(auth_app: TestClient) -> None:
    sid = _create_user_and_session(role="user")
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid))
    resp = auth_app.get("/admin-only")
    assert resp.status_code == 403


def test_require_admin_allows_admin(auth_app: TestClient) -> None:
    sid = _create_user_and_session(role="admin")
    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid))
    resp = auth_app.get("/admin-only")
    assert resp.status_code == 200


# ── IP/UA audit logging ──────────────────────────────────────────


def test_ip_change_creates_audit(auth_app: TestClient) -> None:
    from songmaker_cli.db.engine import get_session_factory
    from songmaker_cli.db.models import AuditLog

    sid = _create_user_and_session()
    factory = get_session_factory()

    with factory() as db:
        from songmaker_cli.db.queries import get_session_with_user
        sess = get_session_with_user(db, sid)
        sess.ip_address = "1.2.3.4"
        db.commit()

    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid))
    auth_app.get("/protected")

    with factory() as db:
        entry = db.query(AuditLog).filter(AuditLog.action == "session_ip_change").first()
        assert entry is not None
        assert "1.2.3.4" in entry.detail


def test_ua_change_creates_audit(auth_app: TestClient) -> None:
    from songmaker_cli.db.engine import get_session_factory
    from songmaker_cli.db.models import AuditLog

    sid = _create_user_and_session()
    factory = get_session_factory()

    with factory() as db:
        from songmaker_cli.db.queries import get_session_with_user
        sess = get_session_with_user(db, sid)
        sess.user_agent = "OldBrowser/1.0"
        db.commit()

    auth_app.cookies.set(SESSION_COOKIE, sign_session_id(sid))
    auth_app.get("/protected", headers={"user-agent": "NewBrowser/2.0"})

    with factory() as db:
        entry = db.query(AuditLog).filter(AuditLog.action == "session_ua_change").first()
        assert entry is not None


# ── IpRateLimiter ────────────────────────────────────────────────


def test_ip_rate_limiter_allows_within_limit() -> None:
    from songmaker_cli.middleware import IpRateLimiter
    limiter = IpRateLimiter(max_requests=3, window_seconds=60)
    assert limiter.is_allowed("10.0.0.1") is True
    assert limiter.is_allowed("10.0.0.1") is True
    assert limiter.is_allowed("10.0.0.1") is True


def test_ip_rate_limiter_blocks_over_limit() -> None:
    from songmaker_cli.middleware import IpRateLimiter
    limiter = IpRateLimiter(max_requests=2, window_seconds=60)
    limiter.is_allowed("10.0.0.1")
    limiter.is_allowed("10.0.0.1")
    assert limiter.is_allowed("10.0.0.1") is False


def test_ip_rate_limiter_different_ips_independent() -> None:
    from songmaker_cli.middleware import IpRateLimiter
    limiter = IpRateLimiter(max_requests=1, window_seconds=60)
    assert limiter.is_allowed("10.0.0.1") is True
    assert limiter.is_allowed("10.0.0.2") is True
    assert limiter.is_allowed("10.0.0.1") is False


def test_ip_rate_limiter_expired_entries_cleaned() -> None:
    from unittest.mock import patch

    from songmaker_cli.middleware import IpRateLimiter
    limiter = IpRateLimiter(max_requests=1, window_seconds=1)
    limiter.is_allowed("10.0.0.1")
    assert limiter.is_allowed("10.0.0.1") is False
    with patch("songmaker_cli.middleware.time") as mock_time:
        mock_time.time.return_value = time.time() + 2
        assert limiter.is_allowed("10.0.0.1") is True


def test_ip_rate_limiter_evicts_stale_ips() -> None:
    from unittest.mock import patch

    from songmaker_cli.middleware import IpRateLimiter
    limiter = IpRateLimiter(max_requests=1, window_seconds=1)
    limiter._MAX_TRACKED_IPS = 3
    limiter._EVICT_BATCH = 2

    base = time.time()
    with patch("songmaker_cli.middleware.time") as mock_time:
        mock_time.time.return_value = base
        for i in range(3):
            limiter.is_allowed(f"10.0.0.{i}")
        assert len(limiter._requests) == 3

        mock_time.time.return_value = base + 2
        limiter.is_allowed("10.0.0.99")
        assert len(limiter._requests) <= 3


# ── get_client_ip ─────────────────────────────────────────────────


def test_get_client_ip_no_trusted_proxies() -> None:
    from songmaker_cli.auth import get_client_ip
    assert get_client_ip("1.2.3.4", "5.6.7.8, 9.10.11.12") == "1.2.3.4"


def test_get_client_ip_rightmost_untrusted() -> None:
    from songmaker_cli import auth as auth_mod
    auth_mod._trusted_proxies = frozenset({"10.0.0.1"})
    try:
        result = get_client_ip("10.0.0.1", "1.2.3.4, 5.6.7.8, 10.0.0.1")
        assert result == "5.6.7.8"
    finally:
        auth_mod.reset_trusted_proxies()


def test_get_client_ip_all_trusted_falls_back() -> None:
    from songmaker_cli import auth as auth_mod
    auth_mod._trusted_proxies = frozenset({"10.0.0.1", "10.0.0.2"})
    try:
        result = get_client_ip("10.0.0.1", "10.0.0.2, 10.0.0.1")
        assert result == "10.0.0.1"
    finally:
        auth_mod.reset_trusted_proxies()


def test_get_client_ip_no_xff() -> None:
    from songmaker_cli import auth as auth_mod
    auth_mod._trusted_proxies = frozenset({"10.0.0.1"})
    try:
        result = get_client_ip("10.0.0.1", None)
        assert result == "10.0.0.1"
    finally:
        auth_mod.reset_trusted_proxies()


def test_ip_rate_limiter_evicts_oldest_when_all_active() -> None:
    from songmaker_cli.middleware import IpRateLimiter
    limiter = IpRateLimiter(max_requests=100, window_seconds=60)
    limiter._MAX_TRACKED_IPS = 3
    limiter._EVICT_BATCH = 2
    for i in range(3):
        limiter.is_allowed(f"10.0.0.{i}")
    assert len(limiter._requests) == 3
    limiter.is_allowed("10.0.0.99")
    assert len(limiter._requests) <= 3
