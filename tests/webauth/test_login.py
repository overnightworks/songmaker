"""What a login hands out, what it refuses, and what a logout takes back."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient
from httpx import Response as ClientResponse
from webauth_arrangement import a_web_auth_config

from webauth.config import WebAuthConfig, install_web_auth_config
from webauth.cookies import verify_csrf_token, verify_session_cookie
from webauth.login import (
    ACCOUNT_LOCKED_DETAIL,
    RETRY_AFTER_HEADER,
    TOO_MANY_LOGIN_ATTEMPTS_DETAIL,
    clear_session_cookies,
    enforce_login_attempt_limits,
    issue_session_cookies,
    password_admits_account,
)
from webauth.passwords import hash_password

SESSION_ID = "session-1"
CLIENT_ADDRESS = "203.0.113.7"
USERNAME = "alice"
PLAIN_HTTP = "http://songmaker.example"
OVER_HTTPS = "https://songmaker.example"

A_CORRECT_PASSWORD = "the-correct-password"
A_WRONG_PASSWORD = "something-else-entirely"


@dataclass(frozen=True)
class CookieApp:
    """One route that issues the session cookies and one that clears them."""

    client: TestClient
    config: WebAuthConfig

    def issue(self) -> ClientResponse:
        return self.client.post("/issue")

    def clear(self) -> ClientResponse:
        return self.client.delete("/session")

    def set_cookie_header(self, response: ClientResponse, name: str) -> str:
        return next(
            value
            for header, value in response.headers.multi_items()
            if header == "set-cookie" and value.startswith(f"{name}=")
        )


def a_cookie_app(*, base_url: str = OVER_HTTPS) -> CookieApp:
    config = a_web_auth_config()
    app = FastAPI()
    install_web_auth_config(app, config)

    @app.post("/issue")
    def issue(request: Request, response: Response) -> dict[str, str]:
        issue_session_cookies(response, request, SESSION_ID, config)
        return {"status": "ok"}

    @app.delete("/session")
    def clear(response: Response) -> dict[str, str]:
        clear_session_cookies(response, config)
        return {"status": "ok"}

    return CookieApp(client=TestClient(app, base_url=base_url), config=config)


@pytest.fixture
def cookie_app() -> CookieApp:
    return a_cookie_app()


def test_the_issued_cookie_carries_a_session_this_deployment_signed(
    cookie_app: CookieApp,
) -> None:
    response = cookie_app.issue()

    cookie = response.cookies[cookie_app.config.session_cookie_name]
    assert verify_session_cookie(cookie, cookie_app.config.signing_key) == SESSION_ID


def test_the_session_cookie_is_kept_from_scripts_and_from_other_sites(
    cookie_app: CookieApp,
) -> None:
    header = cookie_app.set_cookie_header(
        cookie_app.issue(), cookie_app.config.session_cookie_name,
    )

    assert "HttpOnly" in header
    assert "SameSite=strict" in header
    assert f"Max-Age={cookie_app.config.session_max_age_seconds}" in header
    assert "Path=/" in header


def test_the_csrf_token_is_readable_by_the_client_and_bound_to_the_session(
    cookie_app: CookieApp,
) -> None:
    response = cookie_app.issue()

    header = cookie_app.set_cookie_header(response, cookie_app.config.csrf_cookie_name)
    assert "HttpOnly" not in header
    token = response.cookies[cookie_app.config.csrf_cookie_name]
    assert verify_csrf_token(token, SESSION_ID, cookie_app.config.signing_key)


def test_an_https_request_gets_cookies_no_plain_connection_may_carry(
    cookie_app: CookieApp,
) -> None:
    response = cookie_app.issue()

    for name in (cookie_app.config.session_cookie_name, cookie_app.config.csrf_cookie_name):
        assert "Secure" in cookie_app.set_cookie_header(response, name)


def test_a_plain_http_request_gets_cookies_it_can_actually_send_back() -> None:
    app = a_cookie_app(base_url=PLAIN_HTTP)

    response = app.issue()

    for name in (app.config.session_cookie_name, app.config.csrf_cookie_name):
        assert "Secure" not in app.set_cookie_header(response, name)


def test_logging_out_takes_both_cookies_back(cookie_app: CookieApp) -> None:
    cookie_app.issue()

    cookie_app.clear()

    assert cookie_app.config.session_cookie_name not in cookie_app.client.cookies
    assert cookie_app.config.csrf_cookie_name not in cookie_app.client.cookies


@dataclass
class FailuresInMemory:
    """Recent failures, counted the way each budget asks for them."""

    lockout_window_seconds: int
    for_the_account_over_the_lockout_window: int = 0
    from_the_address: int = 0
    for_the_account: int = 0

    def count_recent_failures(
        self, *, ip_address: str, window_seconds: int, username: str | None = None,
    ) -> int:
        if window_seconds == self.lockout_window_seconds:
            return self.for_the_account_over_the_lockout_window
        return self.for_the_account if username else self.from_the_address


def a_login_limit(**failures: int) -> tuple[FailuresInMemory, WebAuthConfig]:
    config = a_web_auth_config(
        login_rate_limit=5, login_lockout_threshold=15,
        login_lockout_window_seconds=3600, login_rate_window_seconds=300,
    )
    return FailuresInMemory(config.login_lockout_window_seconds, **failures), config


def refuse_or_admit(attempts: FailuresInMemory, config: WebAuthConfig) -> None:
    enforce_login_attempt_limits(
        attempts, ip_address=CLIENT_ADDRESS, username=USERNAME, config=config,
    )


def test_an_attempt_within_both_budgets_is_admitted() -> None:
    attempts, config = a_login_limit(
        for_the_account_over_the_lockout_window=14, from_the_address=4, for_the_account=4,
    )

    refuse_or_admit(attempts, config)


def test_an_account_that_kept_failing_is_locked_for_the_lockout_window() -> None:
    attempts, config = a_login_limit(for_the_account_over_the_lockout_window=15)

    with pytest.raises(HTTPException) as refusal:
        refuse_or_admit(attempts, config)

    assert refusal.value.status_code == 429
    assert refusal.value.detail == ACCOUNT_LOCKED_DETAIL
    assert refusal.value.headers[RETRY_AFTER_HEADER] == str(
        config.login_lockout_window_seconds,
    )


@pytest.mark.parametrize(
    "spent",
    [
        pytest.param({"from_the_address": 5}, id="an address that keeps guessing"),
        pytest.param({"for_the_account": 5}, id="one account guessed at repeatedly"),
    ],
)
def test_a_spent_rate_budget_is_refused_for_the_rate_window(spent: dict[str, int]) -> None:
    attempts, config = a_login_limit(**spent)

    with pytest.raises(HTTPException) as refusal:
        refuse_or_admit(attempts, config)

    assert refusal.value.status_code == 429
    assert refusal.value.detail == TOO_MANY_LOGIN_ATTEMPTS_DETAIL
    assert refusal.value.headers[RETRY_AFTER_HEADER] == str(config.login_rate_window_seconds)


def test_a_locked_account_hears_about_the_lockout_not_the_rate_limit() -> None:
    attempts, config = a_login_limit(
        for_the_account_over_the_lockout_window=15, from_the_address=5, for_the_account=5,
    )

    with pytest.raises(HTTPException) as refusal:
        refuse_or_admit(attempts, config)

    assert refusal.value.detail == ACCOUNT_LOCKED_DETAIL


@dataclass(frozen=True)
class StoredAccount:
    password_hash: str
    is_active: bool = True
    id: str = "user-1"
    username: str = USERNAME
    role: str = "user"


AN_ACCOUNT = StoredAccount(password_hash=hash_password(A_CORRECT_PASSWORD))


@pytest.mark.parametrize(
    ("password", "user", "admitted"),
    [
        pytest.param(A_CORRECT_PASSWORD, AN_ACCOUNT, True, id="the account's own password"),
        pytest.param(A_WRONG_PASSWORD, AN_ACCOUNT, False, id="a password that is not it"),
        pytest.param(A_CORRECT_PASSWORD, None, False, id="a username nobody holds"),
        pytest.param(
            A_CORRECT_PASSWORD,
            StoredAccount(password_hash=AN_ACCOUNT.password_hash, is_active=False),
            False,
            id="a deactivated account and its right password",
        ),
    ],
)
def test_only_an_active_account_with_its_own_password_is_admitted(
    password: str, user: StoredAccount | None, admitted: bool,
) -> None:
    assert password_admits_account(password, user) is admitted
