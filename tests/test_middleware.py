"""Tests for session auth dependency and FastAPI integration."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from support.web_app import install_app_context, make_fake_redis, seed_user, web_client
from webauth.cookies import DEFAULT_SESSION_COOKIE_NAME, sign_session_id
from webauth.ports import AuthenticatedUser

from songmaker_cli.auth_dependencies import (
    get_current_user,
    require_admin,
)
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.queries.auth import create_session

_TEST_SECRET = b"a" * 64


@pytest.fixture
def _db(tmp_path: Path):
    return init_db(tmp_path / "test.db")


def _build_auth_app(_db, redis=None):
    from songmaker_cli.app_context import AppContext, get_db_session

    if redis is None:
        redis = make_fake_redis()
    ctx = AppContext(
        db=_db, audio_dir=Path("/tmp/audio"), data_dir=Path("/tmp/data"),
        signing_key=_TEST_SECRET, redis=redis,
    )
    app = FastAPI()
    install_app_context(app, ctx)

    @app.get("/protected")
    def protected(
        user: AuthenticatedUser = Depends(get_current_user),
        db: Session = Depends(get_db_session),
    ):
        db.commit()
        return {
            "username": user.username,
            "role": user.role,
        }

    @app.get("/admin-only")
    def admin_only(user: AuthenticatedUser = Depends(require_admin)):
        return {"username": user.username}

    @app.get("/public")
    def public():
        return {"status": "ok"}

    return app


@pytest.fixture
def auth_app(_db) -> TestClient:
    """Minimal FastAPI app with auth dependency — no middleware stack."""
    app = _build_auth_app(_db)
    return web_client(app, cookies={})


def _make_user_and_session(
    factory,
    role: str = "user", expired: bool = False, created_days_ago: int = 0,
) -> str:
    with factory() as session:
        user = seed_user(session, f"test_{role}_{expired}_{created_days_ago}", role=role)
        if expired:
            expires = datetime.now(timezone.utc) - timedelta(days=1)
        else:
            expires = datetime.now(timezone.utc) + timedelta(days=1)
        user_session = create_session(session, user.id, expires)
        if created_days_ago:
            user_session.created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
        session.commit()
        return user_session.id


@pytest.fixture
def create_session_id(_db):
    from functools import partial
    return partial(_make_user_and_session, _db)


# -- No cookie / bad cookie ---------------------------------------------------


def test_no_cookie_returns_401(auth_app: TestClient) -> None:
    resp = auth_app.get("/protected")
    assert resp.status_code == 401


def test_unsigned_cookie_returns_401(auth_app: TestClient) -> None:
    auth_app.cookies.set(DEFAULT_SESSION_COOKIE_NAME, "raw-no-hmac")
    resp = auth_app.get("/protected")
    assert resp.status_code == 401


def test_nonexistent_session_returns_401(auth_app: TestClient) -> None:
    auth_app.cookies.set(DEFAULT_SESSION_COOKIE_NAME, sign_session_id("nonexistent", _TEST_SECRET))
    resp = auth_app.get("/protected")
    assert resp.status_code == 401


# -- Expiry -------------------------------------------------------------------


def test_expired_session_returns_401(auth_app: TestClient, create_session_id) -> None:
    sid = create_session_id(expired=True)
    auth_app.cookies.set(DEFAULT_SESSION_COOKIE_NAME, sign_session_id(sid, _TEST_SECRET))
    resp = auth_app.get("/protected")
    assert resp.status_code == 401


def test_absolute_max_age_expired(auth_app: TestClient, create_session_id) -> None:
    sid = create_session_id(created_days_ago=31)
    auth_app.cookies.set(DEFAULT_SESSION_COOKIE_NAME, sign_session_id(sid, _TEST_SECRET))
    resp = auth_app.get("/protected")
    assert resp.status_code == 401


# -- Valid session ------------------------------------------------------------


def test_valid_session_returns_200(auth_app: TestClient, create_session_id) -> None:
    sid = create_session_id()
    auth_app.cookies.set(DEFAULT_SESSION_COOKIE_NAME, sign_session_id(sid, _TEST_SECRET))
    resp = auth_app.get("/protected")
    assert resp.status_code == 200
    assert resp.json()["username"].startswith("test_user")


def test_sliding_window_renewal(auth_app: TestClient, create_session_id) -> None:
    from songmaker_cli.db.queries.auth import get_session_with_user

    sid = create_session_id()
    factory = auth_app.app.state.ctx.db

    with factory() as db:
        old_expires = get_session_with_user(db, sid).expires_at

    auth_app.cookies.set(DEFAULT_SESSION_COOKIE_NAME, sign_session_id(sid, _TEST_SECRET))
    auth_app.get("/protected")

    with factory() as db:
        new_expires = get_session_with_user(db, sid).expires_at
        assert new_expires >= old_expires


def test_public_route_no_auth_needed(auth_app: TestClient) -> None:
    resp = auth_app.get("/public")
    assert resp.status_code == 200


# -- Admin dependency ---------------------------------------------------------


def test_require_admin_rejects_regular_user(auth_app: TestClient, create_session_id) -> None:
    sid = create_session_id(role="user")
    auth_app.cookies.set(DEFAULT_SESSION_COOKIE_NAME, sign_session_id(sid, _TEST_SECRET))
    resp = auth_app.get("/admin-only")
    assert resp.status_code == 403


def test_require_admin_allows_admin(auth_app: TestClient, create_session_id) -> None:
    sid = create_session_id(role="admin")
    auth_app.cookies.set(DEFAULT_SESSION_COOKIE_NAME, sign_session_id(sid, _TEST_SECRET))
    resp = auth_app.get("/admin-only")
    assert resp.status_code == 200


@pytest.mark.parametrize("commit_fails", [False, True])
def test_auth_transaction_commits_the_renewal(
    _db, commit_fails, session_commit_failure,
) -> None:
    """defect:#1590: an auth commit failure leaves no renewal."""
    from starlette.requests import Request

    from songmaker_cli.db.queries.auth import get_session_with_user

    sid = _make_user_and_session(_db)
    old_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    with _db() as db:
        record = get_session_with_user(db, sid)
        record.expires_at = old_expiry
        db.commit()

    app = _build_auth_app(_db)
    cookie = f"{DEFAULT_SESSION_COOKIE_NAME}={sign_session_id(sid, _TEST_SECRET)}"
    request = Request({
        "type": "http", "app": app, "method": "GET", "path": "/protected",
        "headers": [(b"cookie", cookie.encode()), (b"user-agent", b"New/2.0")],
        "client": ("192.0.2.2", 1234),
    })

    failure_context = (
        session_commit_failure(_db, message="Auth commit failed")
        if commit_fails else nullcontext()
    )
    with failure_context:
        if commit_fails:
            with pytest.raises(RuntimeError, match="Auth commit failed"):
                get_current_user(request)
        else:
            assert get_current_user(request).username.startswith("test_user")

    with _db() as db:
        record = get_session_with_user(db, sid)
        expiry = record.expires_at.replace(tzinfo=timezone.utc)
        if commit_fails:
            assert expiry == old_expiry
        else:
            assert expiry > old_expiry


@pytest.mark.parametrize("endpoint_write", ["none", "uncommitted", "failed"])
def test_authentication_persists_independently_of_endpoint_writes(_db, endpoint_write) -> None:
    """defect:#1590: the renewal commits; endpoint work never piggybacks."""
    from songmaker_cli.app_context import get_db_session
    from songmaker_cli.db.queries.auth import get_session_with_user, get_user

    sid = _make_user_and_session(_db)
    old_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    with _db() as db:
        record = get_session_with_user(db, sid)
        record.expires_at = old_expiry
        user_id = record.user_id
        original_name = record.user.username
        db.commit()

    app = _build_auth_app(_db)

    @app.get("/no-commit")
    def no_commit(
        user: AuthenticatedUser = Depends(get_current_user),
        db: Session = Depends(get_db_session),
    ):
        if endpoint_write != "none":
            get_user(db, user.id).username = "uncommitted-name"
            db.flush()
        if endpoint_write == "failed":
            raise HTTPException(409, "Endpoint failed")
        return {"username": user.username}

    client = web_client(app, cookies={})
    client.cookies.set(DEFAULT_SESSION_COOKIE_NAME, sign_session_id(sid, _TEST_SECRET))
    response = client.get("/no-commit", headers={"user-agent": "New/2.0"})
    assert response.status_code == (409 if endpoint_write == "failed" else 200)
    assert "set-cookie" not in response.headers
    with _db() as db:
        record = get_session_with_user(db, sid)
        assert record.expires_at.replace(tzinfo=timezone.utc) > old_expiry
        assert get_user(db, user_id).username == original_name


def test_failed_session_renewal_refuses_authentication(_db) -> None:
    """defect:#1590: a vanished row makes touch return False and auth return 401."""
    from sqlalchemy import event
    from starlette.requests import Request

    from songmaker_cli.db.models import UserSession

    sid = _make_user_and_session(_db)
    app = _build_auth_app(_db)
    cookie = f"{DEFAULT_SESSION_COOKIE_NAME}={sign_session_id(sid, _TEST_SECRET)}"
    request = Request({
        "type": "http", "app": app, "method": "GET", "path": "/protected",
        "headers": [(b"cookie", cookie.encode())], "client": ("192.0.2.1", 1234),
    })
    engine = _db.kw["bind"]

    def remove_before_renewal(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE USER_SESSIONS"):
            conn.execute(UserSession.__table__.delete().where(UserSession.id == sid))

    event.listen(engine, "before_cursor_execute", remove_before_renewal)
    try:
        with pytest.raises(HTTPException) as refusal:
            get_current_user(request)
        assert refusal.value.status_code == 401
    finally:
        event.remove(engine, "before_cursor_execute", remove_before_renewal)
