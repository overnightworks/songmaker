"""Tests for session auth middleware and FastAPI dependencies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from songmaker_cli.db.engine import init_db, reset_engine
from songmaker_cli.db.queries import create_session, create_user
from songmaker_cli.middleware import (
    SESSION_COOKIE,
    AuthenticatedUser,
    _is_public,
    get_current_user,
    require_admin,
)
from songmaker_cli.server import create_app


@pytest.fixture()
def _db(tmp_path: Path):
    reset_engine()
    init_db(tmp_path / "test.db")
    yield
    reset_engine()


@pytest.fixture()
def auth_app(tmp_path: Path, _db) -> TestClient:
    output_dir = tmp_path / "_output"
    output_dir.mkdir()
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    app = create_app(output_dir, project_root)
    return TestClient(app, cookies={})


def _create_user_and_session(role: str = "user", active: bool = True) -> str:
    from songmaker_cli.auth import hash_password
    from songmaker_cli.db.engine import get_session_factory

    factory = get_session_factory()
    with factory() as session:
        user = create_user(
            session, f"testuser_{role}_{active}", hash_password("password123"), role=role,
        )
        user.is_active = active
        session.flush()
        expires = datetime.now(timezone.utc) + timedelta(days=30)
        user_session = create_session(session, user.id, expires)
        session.commit()
        return user_session.id


# ── Public routes ───────────────────────────────────────────────────


def test_is_public_root() -> None:
    assert _is_public("/") is True


def test_is_public_login() -> None:
    assert _is_public("/login") is True


def test_is_public_setup() -> None:
    assert _is_public("/setup") is True


def test_static_requires_auth() -> None:
    assert _is_public("/static/foo.js") is False


def test_audio_is_not_public() -> None:
    assert _is_public("/audio/album/song.mp3") is False


def test_is_public_app_assets() -> None:
    assert _is_public("/_app/immutable/chunk.js") is True


def test_is_public_auth_login() -> None:
    assert _is_public("/api/auth/login") is True


def test_is_public_auth_setup() -> None:
    assert _is_public("/api/auth/setup") is True


def test_is_public_auth_setup_required() -> None:
    assert _is_public("/api/auth/setup-required") is True


def test_is_not_public_api_songs() -> None:
    assert _is_public("/api/songs") is False


def test_is_not_public_api_admin() -> None:
    assert _is_public("/api/admin/users") is False


# ── Middleware integration ──────────────────────────────────────────


def test_public_route_no_cookie(auth_app: TestClient) -> None:
    resp = auth_app.get("/")
    assert resp.status_code == 200


def test_protected_route_no_cookie(auth_app: TestClient) -> None:
    resp = auth_app.get("/api/songs")
    assert resp.status_code == 401
    assert resp.json()["error"] == "Authentication required"


def test_protected_route_invalid_session(auth_app: TestClient) -> None:
    auth_app.cookies.set(SESSION_COOKIE, "nonexistent-session-id")
    resp = auth_app.get("/api/songs")
    assert resp.status_code == 401


def test_protected_route_expired_session(auth_app: TestClient) -> None:
    from songmaker_cli.auth import hash_password
    from songmaker_cli.db.engine import get_session_factory

    factory = get_session_factory()
    with factory() as session:
        user = create_user(session, "expired_user", hash_password("password123"))
        expires = datetime.now(timezone.utc) - timedelta(days=1)
        user_session = create_session(session, user.id, expires)
        session.commit()
        session_id = user_session.id

    auth_app.cookies.set(SESSION_COOKIE, session_id)
    resp = auth_app.get("/api/songs")
    assert resp.status_code == 401
    assert resp.json()["error"] == "Session expired"


def test_protected_route_disabled_user(auth_app: TestClient) -> None:
    session_id = _create_user_and_session(active=False)
    auth_app.cookies.set(SESSION_COOKIE, session_id)
    resp = auth_app.get("/api/songs")
    assert resp.status_code == 403
    assert resp.json()["error"] == "Account disabled"


def test_protected_route_valid_session(auth_app: TestClient) -> None:
    session_id = _create_user_and_session()
    auth_app.cookies.set(SESSION_COOKIE, session_id)
    resp = auth_app.get("/api/songs")
    assert resp.status_code == 200


def test_absolute_session_lifetime_expired(auth_app: TestClient) -> None:
    from songmaker_cli.auth import hash_password
    from songmaker_cli.db.engine import get_session_factory

    factory = get_session_factory()
    with factory() as session:
        user = create_user(session, "old_user", hash_password("password123"))
        expires = datetime.now(timezone.utc) + timedelta(days=30)
        user_session = create_session(session, user.id, expires)
        user_session.created_at = datetime.now(timezone.utc) - timedelta(days=91)
        session.commit()
        session_id = user_session.id

    auth_app.cookies.set(SESSION_COOKIE, session_id)
    resp = auth_app.get("/api/songs")
    assert resp.status_code == 401
    assert resp.json()["error"] == "Session expired"


def test_session_sliding_window(auth_app: TestClient) -> None:
    from songmaker_cli.db.engine import get_session_factory
    from songmaker_cli.db.queries import get_session_with_user

    session_id = _create_user_and_session()
    factory = get_session_factory()

    with factory() as db:
        old_session = get_session_with_user(db, session_id)
        old_expires = old_session.expires_at

    auth_app.cookies.set(SESSION_COOKIE, session_id)
    auth_app.get("/api/songs")

    with factory() as db:
        updated_session = get_session_with_user(db, session_id)
        assert updated_session.expires_at >= old_expires


# ── FastAPI dependencies ────────────────────────────────────────────


def test_get_current_user_no_user() -> None:
    from unittest.mock import MagicMock

    request = MagicMock()
    request.state = MagicMock(spec=[])
    with pytest.raises(Exception, match="Authentication required"):
        get_current_user(request)


def test_get_current_user_with_user() -> None:
    from unittest.mock import MagicMock

    user = AuthenticatedUser(id="u1", username="alice", role="user", is_active=True)
    request = MagicMock()
    request.state.user = user
    result = get_current_user(request)
    assert result.username == "alice"


def test_require_admin_with_regular_user() -> None:
    user = AuthenticatedUser(id="u1", username="bob", role="user", is_active=True)
    with pytest.raises(Exception, match="Admin access required"):
        require_admin(user)


def test_require_admin_with_admin_user() -> None:
    user = AuthenticatedUser(id="u1", username="admin", role="admin", is_active=True)
    result = require_admin(user)
    assert result.role == "admin"


def test_dependency_injection_in_endpoint(_db) -> None:
    app = FastAPI()

    @app.get("/test-user")
    def test_endpoint(user: AuthenticatedUser = Depends(get_current_user)):
        return {"username": user.username}

    @app.get("/test-admin")
    def test_admin_endpoint(user: AuthenticatedUser = Depends(require_admin)):
        return {"username": user.username}

    client = TestClient(app)

    resp = client.get("/test-user")
    assert resp.status_code == 401

    resp = client.get("/test-admin")
    assert resp.status_code == 401
