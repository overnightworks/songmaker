"""Tests for auth API endpoints — login, logout, me."""

from __future__ import annotations

import dataclasses
from contextlib import closing
from pathlib import Path

import httpx
import pytest
from conftest import make_test_app, stored_hash, web_client
from fastapi.testclient import TestClient
from webauth.config import install_web_auth_config, installed_web_auth_config
from webauth.cookies import (
    DEFAULT_CSRF_COOKIE_NAME,
    DEFAULT_SESSION_COOKIE_NAME,
    PLAIN_CSRF_COOKIE_NAME,
    PLAIN_SESSION_COOKIE_NAME,
)
from webauth.proxies import TrustedProxies

from songmaker_cli.db.models import UserSession
from songmaker_cli.db.queries.auth import create_user

_PROXY_NETWORK = "172.16.0.0/12"
_TRUSTED_PEER = "172.18.0.1"
_UNTRUSTED_PEER = "203.0.113.50"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path)
    return client


def _seed_admin(client: TestClient) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        create_user(session, "admin", stored_hash("admin12345"), role="admin")
        session.commit()


def _seed_user(client: TestClient, username: str = "alice", active: bool = True) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        user = create_user(session, username, stored_hash("t3stP@ssw0rd"), role="user")
        user.is_active = active
        session.flush()
        session.commit()


def _login(client: TestClient, username: str, password: str) -> TestClient:
    from conftest import login_and_csrf
    login_and_csrf(client, username, password)
    return client


# -- Login --------------------------------------------------------------------


def test_login_success(client: TestClient) -> None:
    _seed_admin(client)
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"
    assert DEFAULT_SESSION_COOKIE_NAME in resp.cookies


def test_login_wrong_password(client: TestClient) -> None:
    _seed_admin(client)
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong12345"})
    assert resp.status_code == 401
    assert "Invalid" in resp.json()["detail"]


def test_login_nonexistent_user(client: TestClient) -> None:
    resp = client.post("/api/auth/login", json={"username": "nobody", "password": "t3stP@ssw0rd"})
    assert resp.status_code == 401


def test_login_disabled_user(client: TestClient) -> None:
    _seed_user(client, "disabled_user", active=False)
    resp = client.post(
        "/api/auth/login", json={"username": "disabled_user", "password": "t3stP@ssw0rd"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


def test_login_with_a_stored_pre_argon2_hash_fails_loudly(client: TestClient) -> None:
    """A hash from before the Argon2id migration is not a wrong password —
    UnknownHashFormatError must surface as a loud 500, never a quiet 401."""
    factory = client.app.state.ctx.db
    with factory() as session:
        create_user(
            session, "admin",
            "$2b$12$C6UzMDM.H6dfI/f/IKcEeO7hwGfCfP01ebE5t1q9b9fjOxnqpBxWC",
            role="admin",
        )
        session.commit()

    with closing(web_client(client.app, raise_server_exceptions=False)) as failing_client:
        resp = failing_client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin12345"},
        )

    assert resp.status_code == 500


def test_login_brute_force_lockout(client: TestClient) -> None:
    _seed_admin(client)
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "admin", "password": "wrong12345"})

    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"})
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


def test_login_lockout_after_sustained_failures(client: TestClient) -> None:
    from songmaker_cli.db.queries.auth import record_login_attempt
    from songmaker_cli.settings import get_settings
    _seed_admin(client)
    threshold = get_settings().login_lockout_threshold
    factory = client.app.state.ctx.db
    with factory() as session:
        for _ in range(threshold):
            record_login_attempt(session, "testclient", "admin", success=False)
        session.commit()

    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"})
    assert resp.status_code == 429
    assert "temporarily locked" in resp.json()["detail"]
    assert "Retry-After" in resp.headers


def _recorded_login_ip(client: TestClient) -> str:
    factory = client.app.state.ctx.db
    with factory() as session:
        from songmaker_cli.db.models import LoginAttempt
        attempt = session.query(LoginAttempt).order_by(LoginAttempt.attempted_at.desc()).first()
        return attempt.ip_address


def _cookie_attributes(resp: httpx.Response, name: str) -> set[str]:
    headers = [h for h in resp.headers.get_list("set-cookie") if h.startswith(f"{name}=")]
    assert len(headers) == 1, f"expected exactly one {name} cookie, got {headers}"
    return {attribute.strip() for attribute in headers[0].split(";")[1:]}


def _trust_docker_network(client: TestClient) -> None:
    install_web_auth_config(
        client.app,
        dataclasses.replace(
            installed_web_auth_config(client.app),
            trusted_proxies=TrustedProxies.parse(_PROXY_NETWORK),
        ),
    )


def _login_from_peer(
    client: TestClient, peer_ip: str, headers: dict[str, str] | list[tuple[str, str]],
) -> httpx.Response:
    """Log in as if the request came from ``peer_ip`` rather than the test transport.

    ``headers`` may be a list of pairs to send the same header field twice —
    the shape a forged chain arrives in.
    """
    peer_client = web_client(client.app, client=(peer_ip, 55000))
    return peer_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin12345"},
        headers=headers,
    )


def test_client_ip_from_forwarded_for_behind_trusted_proxy(client: TestClient) -> None:
    _seed_admin(client)
    _trust_docker_network(client)

    resp = _login_from_peer(
        client, _TRUSTED_PEER, {"x-forwarded-for": "203.0.113.1, 172.18.0.9"},
    )

    assert resp.status_code == 200
    assert _recorded_login_ip(client) == "203.0.113.1"


def test_client_ip_ignores_forwarded_for_from_untrusted_peer(client: TestClient) -> None:
    _seed_admin(client)
    _trust_docker_network(client)

    resp = _login_from_peer(client, _UNTRUSTED_PEER, {"x-forwarded-for": "10.9.9.9"})

    assert resp.status_code == 200
    assert _recorded_login_ip(client) == _UNTRUSTED_PEER


def test_client_ip_merges_repeated_forwarded_for_fields(client: TestClient) -> None:
    """Two X-Forwarded-For fields are one chain: the second field's hop is the
    one closest to the server, so it — not the first field — names the client."""
    _seed_admin(client)
    _trust_docker_network(client)

    resp = _login_from_peer(
        client,
        _TRUSTED_PEER,
        [("x-forwarded-for", "10.9.9.9"), ("x-forwarded-for", "203.0.113.1, 172.18.0.9")],
    )

    assert resp.status_code == 200
    assert _recorded_login_ip(client) == "203.0.113.1"


@pytest.mark.parametrize(
    "forwarded_for", ["   ", "203.0.113.1, ", "garbage", "203.0.113.1, garbage"],
)
def test_login_of_a_malformed_chain_is_recorded_against_the_peer(
    client: TestClient, forwarded_for: str,
) -> None:
    """A lockout counter must never key on an empty or nonsense identity —
    that would pool every malformed visitor into one bucket."""
    _seed_admin(client)
    _trust_docker_network(client)

    resp = _login_from_peer(client, _TRUSTED_PEER, {"x-forwarded-for": forwarded_for})

    assert resp.status_code == 200
    assert _recorded_login_ip(client) == _TRUSTED_PEER


def _with_cookie_secure(client: TestClient, *, secure: bool) -> None:
    install_web_auth_config(
        client.app,
        dataclasses.replace(installed_web_auth_config(client.app), cookie_secure=secure),
    )


def test_login_cookies_are_host_only_and_secure_when_cookie_secure_is_true(
    client: TestClient,
) -> None:
    _seed_admin(client)

    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"})

    assert resp.status_code == 200
    assert "Secure" in _cookie_attributes(resp, DEFAULT_SESSION_COOKIE_NAME)
    assert "Secure" in _cookie_attributes(resp, DEFAULT_CSRF_COOKIE_NAME)


def test_login_cookies_are_plain_and_not_secure_when_cookie_secure_is_false(
    client: TestClient,
) -> None:
    _seed_admin(client)
    _with_cookie_secure(client, secure=False)

    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"})

    assert resp.status_code == 200
    assert "Secure" not in _cookie_attributes(resp, PLAIN_SESSION_COOKIE_NAME)
    assert "Secure" not in _cookie_attributes(resp, PLAIN_CSRF_COOKIE_NAME)


# -- Logout -------------------------------------------------------------------


def test_logout(client: TestClient) -> None:
    _seed_admin(client)
    _login(client, "admin", "admin12345")
    resp = client.delete("/api/auth/session")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_logout_invalidates_session_in_db(client: TestClient) -> None:
    _seed_admin(client)
    _login(client, "admin", "admin12345")
    cookie = client.cookies.get(DEFAULT_SESSION_COOKIE_NAME)
    resp = client.delete("/api/auth/session")
    assert resp.status_code == 200

    other = web_client(client.app, cookies={})
    other.cookies.set(DEFAULT_SESSION_COOKIE_NAME, cookie)
    resp = other.get("/api/auth/me")
    assert resp.status_code == 401


def test_logout_without_session(client: TestClient) -> None:
    resp = client.delete("/api/auth/session")
    assert resp.status_code in (401, 403)


# -- Me -----------------------------------------------------------------------


def test_me_authenticated(client: TestClient) -> None:
    _seed_admin(client)
    _login(client, "admin", "admin12345")
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin"
    assert data["role"] == "admin"


def test_me_unauthenticated(client: TestClient) -> None:
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_login_creates_a_persisted_usable_session(client: TestClient) -> None:
    """defect:#1590: issued cookies authenticate a committed session."""
    _seed_admin(client)
    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"},
    )
    assert response.status_code == 200
    user_id = _get_user_id(client, "admin")
    with client.app.state.ctx.db() as session:
        assert session.query(UserSession).filter_by(user_id=user_id).count() == 1
    with closing(web_client(client.app, cookies=response.cookies)) as replay:
        response_me = replay.get("/api/auth/me")
    assert response_me.status_code == 200
    assert response_me.json()["username"] == "admin"


def test_second_login_keeps_existing_sessions(client: TestClient) -> None:
    """defect:#1590: both committed sessions remain usable below the cap."""

    _seed_admin(client)
    user_id = _get_user_id(client, "admin")

    first = web_client(client.app, cookies={})
    second = web_client(client.app, cookies={})
    assert first.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"},
    ).status_code == 200
    assert second.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"},
    ).status_code == 200

    with client.app.state.ctx.db() as session:
        assert session.query(UserSession).filter_by(user_id=user_id).count() == 2
    assert first.get("/api/auth/me").status_code == 200
    assert second.get("/api/auth/me").status_code == 200


def test_login_prunes_oldest_session_over_cap(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """defect:#1590: pruning deletes only the oldest session and rejects its cookie."""
    from songmaker_cli.settings import get_settings

    monkeypatch.setattr(get_settings(), "max_concurrent_sessions_per_user", 2)
    _seed_admin(client)
    user_id = _get_user_id(client, "admin")

    first = web_client(client.app, cookies={})
    second = web_client(client.app, cookies={})
    third = web_client(client.app, cookies={})
    assert first.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"},
    ).status_code == 200
    with client.app.state.ctx.db() as session:
        oldest_sid = session.query(UserSession).filter_by(user_id=user_id).one().id
    assert second.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"},
    ).status_code == 200
    assert third.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"},
    ).status_code == 200

    assert first.get("/api/auth/me").status_code == 401
    assert second.get("/api/auth/me").status_code == 200
    assert third.get("/api/auth/me").status_code == 200

    factory = client.app.state.ctx.db
    with factory() as session:
        remaining = session.query(UserSession).filter_by(user_id=user_id).all()
        remaining_ids = {row.id for row in remaining}
        assert len(remaining_ids) == 2
        assert oldest_sid not in remaining_ids


def test_login_commit_failure_leaves_no_session_or_cookie(
    client: TestClient, session_commit_failure,
) -> None:
    """defect:#1590: a failed session commit leaves no usable authentication."""
    from webauth.cookies import sign_session_id

    from songmaker_cli.app_context import get_db_session

    _seed_admin(client)
    factory = client.app.state.ctx.db
    attempted_cookies: list[str] = []
    config = installed_web_auth_config(client.app)

    def observe_session(db) -> None:
        record = db.query(UserSession).one_or_none()
        if record is not None:
            attempted_cookies.append(sign_session_id(record.id, config.signing_key))

    def failing_session():
        with factory() as db, session_commit_failure(
            db,
            observe=observe_session,
            when=lambda session: session.query(UserSession).first() is not None,
        ):
            yield db

    client.app.dependency_overrides[get_db_session] = failing_session
    try:
        with closing(web_client(client.app, raise_server_exceptions=False)) as failing_client:
            response = failing_client.post(
                "/api/auth/login", json={"username": "admin", "password": "admin12345"},
            )
    finally:
        del client.app.dependency_overrides[get_db_session]

    assert response.status_code == 500
    assert DEFAULT_SESSION_COOKIE_NAME not in response.cookies
    assert len(attempted_cookies) == 1
    with factory() as session:
        assert session.query(UserSession).count() == 0
    with closing(web_client(client.app, cookies={
        DEFAULT_SESSION_COOKIE_NAME: attempted_cookies[0],
    })) as replay:
        assert replay.get("/api/auth/me").status_code == 401


def test_logout_removes_the_session_and_rejects_its_cookie(
    client: TestClient,
) -> None:
    """defect:#1590: logout persists revocation before clearing the cookie."""
    _seed_admin(client)
    _login(client, "admin", "admin12345")

    cookie = client.cookies[DEFAULT_SESSION_COOKIE_NAME]
    user_id = _get_user_id(client, "admin")
    factory = client.app.state.ctx.db
    with factory() as session:
        assert session.query(UserSession).filter_by(user_id=user_id).count() == 1

    resp = client.delete("/api/auth/session")

    assert resp.status_code == 200
    with factory() as session:
        assert session.query(UserSession).filter_by(user_id=user_id).all() == []
    with closing(web_client(client.app, cookies={DEFAULT_SESSION_COOKIE_NAME: cookie})) as replay:
        assert replay.get("/api/auth/me").status_code == 401


def _get_user_id(client: TestClient, username: str) -> str:
    factory = client.app.state.ctx.db
    with factory() as session:
        from songmaker_cli.db.queries.auth import get_user_by_username
        user = get_user_by_username(session, username)
        return user.id


@pytest.mark.parametrize("operation", ["login", "logout"])
def test_session_deletion_failure_rolls_back_auth_changes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, operation: str, session_deletion_failure,
) -> None:
    """defect:#1590: DB failure leaves password, sessions and cookies unchanged."""

    from songmaker_cli.db.models import User
    from songmaker_cli.settings import get_settings

    monkeypatch.setattr(get_settings(), "max_concurrent_sessions_per_user", 1)
    _seed_admin(client)
    _login(client, "admin", "admin12345")
    factory = client.app.state.ctx.db
    with factory() as db:
        old_ids = {row.id for row in db.query(UserSession).all()}
        password_hash = db.query(User).one().password_hash

    method, path, payload = {
        "login": ("POST", "/api/auth/login", {
            "username": "admin", "password": "admin12345",
        }),
        "logout": ("DELETE", "/api/auth/session", None),
    }[operation]
    with session_deletion_failure(factory):
        with closing(web_client(client.app, raise_server_exceptions=False)) as failing_client:
            failing_client.cookies.update(client.cookies)
            failing_client.headers.update(client.headers)
            response = failing_client.request(method, path, json=payload)

    assert response.status_code == 500
    assert "set-cookie" not in response.headers
    with factory() as db:
        assert {row.id for row in db.query(UserSession).all()} == old_ids
        assert db.query(User).one().password_hash == password_hash
    assert client.get("/api/auth/me").status_code == 200
    assert client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"},
    ).status_code == 200


def test_me_persists_renewal_without_reissuing_browser_cookie(client: TestClient) -> None:
    """defect:#1590: GET renewal survives in a fresh DB transaction."""
    from datetime import datetime, timedelta, timezone

    _seed_admin(client)
    _login(client, "admin", "admin12345")
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
    window = timedelta(seconds=installed_web_auth_config(client.app).session_max_age_seconds)
    with factory() as db:
        expiry = db.get(UserSession, session_id).expires_at.replace(tzinfo=timezone.utc)
        assert before + window <= expiry <= after + window
        assert expiry > old_expiry
