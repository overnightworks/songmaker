"""What a signed session cookie proves, and what the application hears about it."""

from __future__ import annotations

from datetime import timedelta

import pytest
from webauth_arrangement import (
    ADMIN_ROLE,
    CLIENT_ADDRESS,
    CLIENT_USER_AGENT,
    MEMBER_ROLE,
    SESSION_ID,
    AuthApp,
    FakeSessionRecord,
    FakeUser,
    a_session,
    an_auth_app,
)

from webauth.cookies import sign_session_id
from webauth.dependencies import (
    ACCOUNT_DISABLED_DETAIL,
    ADMIN_REQUIRED_DETAIL,
    AUTHENTICATION_REQUIRED_DETAIL,
    INVALID_SESSION_DETAIL,
    MAX_SESSION_COOKIE_CHARS,
    SESSION_EXPIRED_DETAIL,
    AuthenticatedUser,
)
from webauth.ports import SessionIdentityChange, SessionIdentityChanged


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


def test_a_route_can_name_the_session_the_request_proved_it_holds(
    auth_app: AuthApp,
) -> None:
    response = auth_app.get("/session-id", cookie=auth_app.signed_cookie())

    assert response.status_code == 200
    assert response.json() == {"session_id": SESSION_ID}


@pytest.mark.parametrize(
    ("record", "cookie", "status", "detail"),
    [
        pytest.param(a_session(), None, 401, AUTHENTICATION_REQUIRED_DETAIL, id="no cookie"),
        pytest.param(
            a_session(remaining=-timedelta(seconds=1)),
            SESSION_ID,
            401,
            SESSION_EXPIRED_DETAIL,
            id="a session past its expiry",
        ),
        pytest.param(
            a_session(user=FakeUser(is_active=False)),
            SESSION_ID,
            403,
            ACCOUNT_DISABLED_DETAIL,
            id="a deactivated account",
        ),
    ],
)
def test_no_session_is_named_where_no_account_would_be_admitted(
    record: FakeSessionRecord, cookie: str | None, status: int, detail: str,
) -> None:
    app = an_auth_app(record)

    response = app.get(
        "/session-id", cookie=None if cookie is None else app.signed_cookie(),
    )

    assert response.status_code == status
    assert response.json()["detail"] == detail
