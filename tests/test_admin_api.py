"""Tests for admin API endpoints — user CRUD, sessions, login attempts."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from songmaker_cli.auth import hash_password
from songmaker_cli.db.engine import get_session_factory, init_db, reset_engine
from songmaker_cli.db.queries import create_user
from songmaker_cli.middleware import SESSION_COOKIE
from songmaker_cli.server import create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    reset_engine()
    output_dir = tmp_path / "_output"
    output_dir.mkdir()
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    init_db(output_dir / "songmaker.db")
    app = create_app(output_dir, project_root, auth_enabled=True)
    yield TestClient(app, cookies={})
    reset_engine()


def _login_as_admin(client: TestClient) -> None:
    factory = get_session_factory()
    with factory() as session:
        create_user(session, "admin", hash_password("admin12345"), role="admin")
        session.commit()
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"})
    assert resp.status_code == 200


def _login_as_user(client: TestClient) -> None:
    factory = get_session_factory()
    with factory() as session:
        create_user(session, "regular", hash_password("user123456"), role="user")
        session.commit()
    resp = client.post("/api/auth/login", json={"username": "regular", "password": "user123456"})
    assert resp.status_code == 200


# ── Access control ──────────────────────────────────────────────────


def test_admin_endpoints_require_auth(client: TestClient) -> None:
    resp = client.get("/api/admin/users")
    assert resp.status_code == 401


def test_admin_endpoints_require_admin_role(client: TestClient) -> None:
    _login_as_user(client)
    resp = client.get("/api/admin/users")
    assert resp.status_code == 403


# ── List users ──────────────────────────────────────────────────────


def test_list_users(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.get("/api/admin/users")
    assert resp.status_code == 200
    users = resp.json()
    assert len(users) == 1
    assert users[0]["username"] == "admin"
    assert "password_hash" not in users[0]


# ── Create user ─────────────────────────────────────────────────────


def test_create_user(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "newuser", "password": "password123", "role": "user"},
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "newuser"
    assert resp.json()["role"] == "user"


def test_create_user_duplicate(client: TestClient) -> None:
    _login_as_admin(client)
    client.post(
        "/api/admin/users",
        json={"username": "dup", "password": "password123"},
    )
    resp = client.post(
        "/api/admin/users",
        json={"username": "dup", "password": "password123"},
    )
    assert resp.status_code == 409


def test_create_user_invalid_role(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "password123", "role": "superadmin"},
    )
    assert resp.status_code == 422


# ── Update user ─────────────────────────────────────────────────────


def test_update_user_role(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "password123"},
    )
    user_id = resp.json()["id"]

    resp = client.put(f"/api/admin/users/{user_id}", json={"role": "admin"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_update_user_deactivate(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "password123"},
    )
    user_id = resp.json()["id"]

    resp = client.put(f"/api/admin/users/{user_id}", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_update_user_password(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "password123"},
    )
    user_id = resp.json()["id"]

    resp = client.put(f"/api/admin/users/{user_id}", json={"password": "newpass12345"})
    assert resp.status_code == 200


def test_update_user_not_found(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.put("/api/admin/users/nonexistent", json={"role": "admin"})
    assert resp.status_code == 404


def test_update_user_invalid_role(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "password123"},
    )
    user_id = resp.json()["id"]

    resp = client.put(f"/api/admin/users/{user_id}", json={"role": "superadmin"})
    assert resp.status_code == 422


def test_cannot_deactivate_self(client: TestClient) -> None:
    _login_as_admin(client)
    me = client.get("/api/auth/me").json()
    resp = client.put(f"/api/admin/users/{me['id']}", json={"is_active": False})
    assert resp.status_code == 400
    assert "own account" in resp.json()["detail"]


def test_cannot_demote_self(client: TestClient) -> None:
    _login_as_admin(client)
    me = client.get("/api/auth/me").json()
    resp = client.put(f"/api/admin/users/{me['id']}", json={"role": "user"})
    assert resp.status_code == 400
    assert "own admin" in resp.json()["detail"]


# ── Delete (deactivate) user ────────────────────────────────────────


def test_deactivate_user(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "password123"},
    )
    user_id = resp.json()["id"]

    resp = client.delete(f"/api/admin/users/{user_id}")
    assert resp.status_code == 200

    users = client.get("/api/admin/users").json()
    bob = next(u for u in users if u["username"] == "bob")
    assert bob["is_active"] is False


def test_deactivate_user_not_found(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.delete("/api/admin/users/nonexistent")
    assert resp.status_code == 404


def test_cannot_deactivate_self_via_delete(client: TestClient) -> None:
    _login_as_admin(client)
    me = client.get("/api/auth/me").json()
    resp = client.delete(f"/api/admin/users/{me['id']}")
    assert resp.status_code == 400


# ── Login attempts ──────────────────────────────────────────────────


def test_list_login_attempts(client: TestClient) -> None:
    _login_as_admin(client)
    client.post("/api/auth/login", json={"username": "nobody", "password": "wrong12345"})
    resp = client.get("/api/admin/login-attempts")
    assert resp.status_code == 200
    attempts = resp.json()
    assert len(attempts) >= 1


# ── Sessions ────────────────────────────────────────────────────────


def test_list_sessions(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.get("/api/admin/sessions")
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) >= 1
    assert sessions[0]["username"] == "admin"


def test_force_logout(client: TestClient) -> None:
    _login_as_admin(client)

    factory = get_session_factory()
    with factory() as session:
        create_user(session, "victim", hash_password("password123"))
        session.commit()

    other_client = TestClient(client.app, cookies={})
    other_client.post("/api/auth/login", json={"username": "victim", "password": "password123"})
    victim_cookie = other_client.cookies.get(SESSION_COOKIE)

    resp = client.delete(f"/api/admin/sessions/{victim_cookie}")
    assert resp.status_code == 200

    other_client.cookies.set(SESSION_COOKIE, victim_cookie)
    resp = other_client.get("/api/auth/me")
    assert resp.status_code == 401
