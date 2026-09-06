"""What the session cache may answer for, and what it may never hide."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from webauth_arrangement import (
    CLIENT_ADDRESS,
    CLIENT_USER_AGENT,
    MEMBER_ROLE,
    SESSION_ID,
    FakeUser,
    a_session,
    a_session_cache,
    a_session_cache_failing_on,
    an_auth_app,
)

from webauth.dependencies import ACCOUNT_DISABLED_DETAIL, SESSION_EXPIRED_DETAIL
from webauth.ports import SessionIdentityChange
from webauth.session_store import SessionCache

CACHED_MAX_AGE_SECONDS = 3600
A_STORED_SESSION_STILL_STANDS = a_session


def a_cached_session(
    cache: SessionCache,
    *,
    user: FakeUser | None = None,
    created_at: datetime | None = None,
    ip_address: str = CLIENT_ADDRESS,
) -> None:
    now = datetime.now(timezone.utc)
    account = user or FakeUser()
    cache.store(
        SESSION_ID,
        account.id,
        account.username,
        account.role,
        account.is_active,
        ip_address,
        CLIENT_USER_AGENT,
        now + timedelta(minutes=30),
        now - timedelta(minutes=5) if created_at is None else created_at,
        CACHED_MAX_AGE_SECONDS,
    )


def test_a_cached_session_names_its_account_without_asking_the_store() -> None:
    cache = a_session_cache()
    a_cached_session(cache)
    app = an_auth_app(None, cache)

    response = app.get("/me", cookie=app.signed_cookie())

    assert response.status_code == 200
    assert response.json() == {"username": "alice", "role": MEMBER_ROLE}


@pytest.mark.parametrize(
    "strip_offset",
    [
        pytest.param(False, id="a creation time stored with its offset"),
        pytest.param(True, id="a creation time stored bare"),
    ],
)
def test_a_cached_session_past_the_absolute_limit_is_refused(strip_offset: bool) -> None:
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    cache = a_session_cache()
    a_cached_session(
        cache,
        created_at=two_days_ago.replace(tzinfo=None) if strip_offset else two_days_ago,
    )
    app = an_auth_app(A_STORED_SESSION_STILL_STANDS(), cache)

    response = app.get("/me", cookie=app.signed_cookie())

    assert response.status_code == 401
    assert response.json()["detail"] == SESSION_EXPIRED_DETAIL


def test_an_account_deactivated_in_the_cache_is_refused_its_live_session() -> None:
    cache = a_session_cache()
    a_cached_session(cache, user=FakeUser(is_active=False))
    app = an_auth_app(A_STORED_SESSION_STILL_STANDS(), cache)

    response = app.get("/me", cookie=app.signed_cookie())

    assert response.status_code == 403
    assert response.json()["detail"] == ACCOUNT_DISABLED_DETAIL


def test_a_cache_that_cannot_be_read_lets_the_store_answer() -> None:
    app = an_auth_app(a_session(), a_session_cache_failing_on("get"))

    response = app.get("/me", cookie=app.signed_cookie())

    assert response.status_code == 200
    assert response.json() == {"username": "alice", "role": MEMBER_ROLE}


def test_a_cache_that_cannot_be_written_still_serves_the_request() -> None:
    cache = a_session_cache_failing_on("expire")
    a_cached_session(cache)
    app = an_auth_app(None, cache)

    response = app.get("/me", cookie=app.signed_cookie())

    assert response.status_code == 200
    assert response.json() == {"username": "alice", "role": MEMBER_ROLE}


def test_a_session_the_store_answered_for_is_cached_for_the_next_request() -> None:
    cache = a_session_cache()
    app = an_auth_app(a_session(), cache)

    app.get("/me", cookie=app.signed_cookie())

    cached = cache.get(SESSION_ID)
    assert cached is not None
    assert cached.user_id == "user-1"
    assert cached.username == "alice"


def test_a_cached_session_arriving_from_a_new_address_is_reported_and_remembered() -> None:
    cache = a_session_cache()
    a_cached_session(cache, ip_address="203.0.113.9")
    app = an_auth_app(None, cache)

    app.get("/me", cookie=app.signed_cookie())

    assert [event.change for event in app.audit.events] == [SessionIdentityChange.IP_ADDRESS]
    assert cache.get(SESSION_ID).ip_address == CLIENT_ADDRESS
