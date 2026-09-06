"""What a signed session cookie proves, and what the application hears about it."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from webauth_arrangement import a_web_auth_config

from webauth.config import install_web_auth_config
from webauth.cookies import sign_session_id
from webauth.dependencies import (
    ACCOUNT_DISABLED_DETAIL,
    ADMIN_REQUIRED_DETAIL,
    AUTHENTICATION_REQUIRED_DETAIL,
    INVALID_SESSION_DETAIL,
    MAX_SESSION_COOKIE_CHARS,
    SESSION_EXPIRED_DETAIL,
    AuthenticatedUser,
    current_user_dependency,
)
from webauth.ports import SessionIdentityChange, SessionIdentityChanged

SESSION_ID = "session-1"
CLIENT_ADDRESS = "testclient"
CLIENT_USER_AGENT = "TestBrowser/1.0"
ADMIN_ROLE = "admin"
MEMBER_ROLE = "user"


@dataclass
class FakeUser:
    id: str = "user-1"
    username: str = "alice"
    role: str = MEMBER_ROLE
    is_active: bool = True
    password_hash: str = "unused"


@dataclass
class FakeSessionRecord:
    id: str
    user: FakeUser
    created_at: datetime
    expires_at: datetime
    ip_address: str = CLIENT_ADDRESS
    user_agent: str = CLIENT_USER_AGENT

    @property
    def user_id(self) -> str:
        return self.user.id


@dataclass
class SessionRecordsInMemory:
    """The one stored session, renewed in place and never committed."""

    record: FakeSessionRecord | None

    def load(self, session_id: str) -> FakeSessionRecord | None:
        if self.record is None or self.record.id != session_id:
            return None
        return self.record

    def touch(
        self,
        record: FakeSessionRecord,
        *,
        ip_address: str,
        user_agent: str,
        expires_at: datetime,
    ) -> None:
        record.ip_address = ip_address
        record.user_agent = user_agent
        record.expires_at = expires_at


@dataclass
class RecordingAuditSink:
    events: list[SessionIdentityChanged] = field(default_factory=list)

    def session_identity_changed(self, event: SessionIdentityChanged) -> None:
        self.events.append(event)


@dataclass
class AuthApp:
    """A minimal application serving one protected and one admin-only route."""

    client: TestClient
    sessions: SessionRecordsInMemory
    audit: RecordingAuditSink
    authenticated: list[AuthenticatedUser]
    signing_key: bytes

    def get(self, path: str, *, cookie: str | None = None) -> Response:
        headers = {} if cookie is None else {"cookie": f"session_id={cookie}"}
        return self.client.get(path, headers=headers)

    def signed_cookie(self, session_id: str = SESSION_ID) -> str:
        return sign_session_id(session_id, self.signing_key)


def a_session(
    *,
    age: timedelta = timedelta(minutes=5),
    remaining: timedelta = timedelta(minutes=30),
    user: FakeUser | None = None,
    ip_address: str = CLIENT_ADDRESS,
    user_agent: str = CLIENT_USER_AGENT,
) -> FakeSessionRecord:
    now = datetime.now(timezone.utc)
    return FakeSessionRecord(
        id=SESSION_ID,
        user=user or FakeUser(),
        created_at=now - age,
        expires_at=now + remaining,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def an_auth_app(record: FakeSessionRecord | None) -> AuthApp:
    config = a_web_auth_config(admin_role=ADMIN_ROLE)
    sessions = SessionRecordsInMemory(record)
    audit = RecordingAuditSink()
    authenticated: list[AuthenticatedUser] = []

    dependencies = current_user_dependency(
        session_store=lambda: sessions,
        audit_sink=lambda: audit,
        on_authenticated=authenticated.append,
    )

    app = FastAPI()
    install_web_auth_config(app, config)

    @app.get("/me")
    def me(user: AuthenticatedUser = Depends(dependencies.current_user)) -> dict[str, str]:
        return {"username": user.username, "role": user.role}

    @app.get("/admin")
    def admin(user: AuthenticatedUser = Depends(dependencies.admin_user)) -> dict[str, str]:
        return {"username": user.username}

    return AuthApp(
        client=TestClient(app, cookies={}, headers={"user-agent": CLIENT_USER_AGENT}),
        sessions=sessions,
        audit=audit,
        authenticated=authenticated,
        signing_key=config.signing_key,
    )


@pytest.fixture
def auth_app() -> AuthApp:
    return an_auth_app(a_session())


def test_a_signed_cookie_names_the_account_behind_the_request(auth_app: AuthApp) -> None:
    response = auth_app.get("/me", cookie=auth_app.signed_cookie())

    assert response.status_code == 200
    assert response.json() == {"username": "alice", "role": MEMBER_ROLE}


def test_the_application_is_told_which_account_authenticated(auth_app: AuthApp) -> None:
    auth_app.get("/me", cookie=auth_app.signed_cookie())

    assert auth_app.authenticated == [
        AuthenticatedUser(id="user-1", username="alice", role=MEMBER_ROLE, is_active=True),
    ]


@pytest.mark.parametrize(
    ("cookie", "detail"),
    [
        pytest.param(None, AUTHENTICATION_REQUIRED_DETAIL, id="no cookie at all"),
        pytest.param("", AUTHENTICATION_REQUIRED_DETAIL, id="an empty cookie"),
        pytest.param(
            "x" * (MAX_SESSION_COOKIE_CHARS + 1),
            AUTHENTICATION_REQUIRED_DETAIL,
            id="a cookie longer than any this signs",
        ),
        pytest.param("unsigned", INVALID_SESSION_DETAIL, id="a cookie without a signature"),
        pytest.param(
            sign_session_id(SESSION_ID, b"a different signing key entirely"),
            INVALID_SESSION_DETAIL,
            id="a cookie signed with another key",
        ),
    ],
)
def test_a_cookie_that_was_not_issued_here_authenticates_nobody(
    auth_app: AuthApp, cookie: str | None, detail: str,
) -> None:
    response = auth_app.get("/me", cookie=cookie)

    assert response.status_code == 401
    assert response.json()["detail"] == detail


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(None, id="a session the store does not know"),
        pytest.param(a_session(remaining=-timedelta(seconds=1)), id="a session past its expiry"),
        pytest.param(a_session(age=timedelta(days=2)), id="a session past the absolute limit"),
    ],
)
def test_a_session_that_no_longer_stands_is_refused(record: FakeSessionRecord | None) -> None:
    app = an_auth_app(record)

    response = app.get("/me", cookie=app.signed_cookie())

    assert response.status_code == 401
    assert response.json()["detail"] == SESSION_EXPIRED_DETAIL


def test_a_deactivated_account_is_refused_its_own_live_session() -> None:
    app = an_auth_app(a_session(user=FakeUser(is_active=False)))

    response = app.get("/me", cookie=app.signed_cookie())

    assert response.status_code == 403
    assert response.json()["detail"] == ACCOUNT_DISABLED_DETAIL


def test_a_served_request_renews_its_session_in_place(auth_app: AuthApp) -> None:
    before = auth_app.sessions.record.expires_at

    auth_app.get("/me", cookie=auth_app.signed_cookie())

    assert auth_app.sessions.record.expires_at > before


def test_a_session_arriving_from_a_new_address_is_reported_once(auth_app: AuthApp) -> None:
    auth_app.sessions.record.ip_address = "203.0.113.9"

    auth_app.get("/me", cookie=auth_app.signed_cookie())

    assert auth_app.audit.events == [
        SessionIdentityChanged(
            change=SessionIdentityChange.IP_ADDRESS,
            user_id="user-1",
            session_id=SESSION_ID,
            previous="203.0.113.9",
            current=CLIENT_ADDRESS,
        ),
    ]


def test_a_session_arriving_from_a_new_agent_is_reported_once(auth_app: AuthApp) -> None:
    auth_app.sessions.record.user_agent = "OldBrowser/1.0"

    auth_app.get("/me", cookie=auth_app.signed_cookie())

    assert auth_app.audit.events == [
        SessionIdentityChanged(
            change=SessionIdentityChange.USER_AGENT,
            user_id="user-1",
            session_id=SESSION_ID,
            previous="OldBrowser/1.0",
            current=CLIENT_USER_AGENT,
        ),
    ]


def test_a_session_stored_without_an_origin_reports_no_change() -> None:
    app = an_auth_app(a_session(ip_address="", user_agent=""))

    app.get("/me", cookie=app.signed_cookie())

    assert app.audit.events == []


def test_an_unchanged_origin_reports_nothing(auth_app: AuthApp) -> None:
    auth_app.get("/me", cookie=auth_app.signed_cookie())

    assert auth_app.audit.events == []


def test_the_admin_route_admits_the_configured_admin_role() -> None:
    app = an_auth_app(a_session(user=FakeUser(role=ADMIN_ROLE)))

    response = app.get("/admin", cookie=app.signed_cookie())

    assert response.status_code == 200
    assert response.json() == {"username": "alice"}


def test_the_admin_route_refuses_every_other_role(auth_app: AuthApp) -> None:
    response = auth_app.get("/admin", cookie=auth_app.signed_cookie())

    assert response.status_code == 403
    assert response.json()["detail"] == ADMIN_REQUIRED_DETAIL


def test_the_admin_route_refuses_the_same_cookie_the_protected_route_refuses(
    auth_app: AuthApp,
) -> None:
    response = auth_app.get("/admin")

    assert response.status_code == 401
    assert response.json()["detail"] == AUTHENTICATION_REQUIRED_DETAIL
