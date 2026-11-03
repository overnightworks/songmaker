"""The signed-in account endpoint, and the password-era routes that are gone."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.web_app import make_test_app, seed_session, seed_user
from webauth.config import installed_web_auth_config

from songmaker_cli.db.models import UserSession


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path)
    return client


def _seed_admin(client: TestClient) -> None:
    with client.app.state.ctx.db() as session:
        seed_user(session, "admin", role="admin")
        session.commit()


def test_me_authenticated(client: TestClient) -> None:
    _seed_admin(client)
    seed_session(client, "admin")

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert (response.json()["username"], response.json()["role"]) == ("admin", "admin")


def test_me_names_the_account_console_under_the_issuer(client: TestClient) -> None:
    _seed_admin(client)
    seed_session(client, "admin")

    assert client.get("/api/auth/me").json()["account_console_url"] == (
        "https://issuer.test/realms/test/account"
    )


def test_me_unauthenticated(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_me_persists_renewal_without_reissuing_browser_cookie(client: TestClient) -> None:
    """defect:#1590: GET renewal survives in a fresh DB transaction."""
    _seed_admin(client)
    seed_session(client, "admin")
    old_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    factory = client.app.state.ctx.db
    with factory.begin() as db:
        record = db.query(UserSession).one()
        session_id = record.id
        record.expires_at = old_expiry

    before = datetime.now(timezone.utc)
    response = client.get("/api/auth/me")
    after = datetime.now(timezone.utc)

    assert response.status_code == 200
    assert response.json()["username"] == "admin"
    assert "set-cookie" not in response.headers
    idle = timedelta(seconds=installed_web_auth_config(client.app).session_lifetime.idle_seconds)
    with factory() as db:
        expiry = db.get(UserSession, session_id).expires_at.replace(tzinfo=timezone.utc)
        whole_second = timedelta(seconds=1)  # the library reads the clock in whole seconds
        assert before + idle - whole_second <= expiry <= after + idle
        assert expiry > old_expiry


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/setup"),
        ("GET", "/api/auth/setup-required"),
        ("PUT", "/api/auth/password"),
        ("DELETE", "/api/auth/session"),
        ("GET", "/api/admin/users"),
        ("GET", "/api/admin/sessions"),
        ("GET", "/api/admin/login-attempts"),
    ],
)
def test_the_password_era_routes_are_gone(client: TestClient, method: str, path: str) -> None:
    _seed_admin(client)
    seed_session(client, "admin")

    response = client.request(method, path, json={})

    assert response.status_code in {404, 405}
