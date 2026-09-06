"""Signing in and out, minus everything that touches a transaction.

The application keeps the login route itself: its advisory lock, the failed
attempt it commits before refusing, and when the request's work becomes
durable. What is left over lives here — the cookies a signed-in browser
carries, the failure budget an address has spent, and whether a password
admits an account at all. None of it reads or writes a store of its own, so
none of it can leave half a login behind.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from fastapi import HTTPException

from webauth.cookies import generate_csrf_token, sign_session_id
from webauth.passwords import verify_password_constant_time
from webauth.proxies import request_is_https

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from webauth.config import WebAuthConfig
    from webauth.ports import LoginAttemptStore, UserRecord

ACCOUNT_LOCKED_DETAIL: Final = (
    "Account temporarily locked due to repeated failed attempts. Try again later."
)
TOO_MANY_LOGIN_ATTEMPTS_DETAIL: Final = "Too many login attempts. Try again later."
RETRY_AFTER_HEADER: Final = "Retry-After"

COOKIE_PATH: Final = "/"
COOKIE_SAME_SITE: Final = "strict"


def issue_session_cookies(
    response: Response,
    request: Request,
    session_id: str,
    config: WebAuthConfig,
) -> None:
    """Hand the browser its signed session and the CSRF token bound to it.

    Only the session cookie is kept from scripts: the CSRF token has to be
    readable, because the double-submit check compares it against a header the
    client sends back itself.
    """
    secure = request_is_https(request)
    max_age = config.session_max_age_seconds
    response.set_cookie(
        config.session_cookie_name,
        sign_session_id(session_id, config.signing_key),
        max_age=max_age,
        httponly=True,
        samesite=COOKIE_SAME_SITE,
        secure=secure,
        path=COOKIE_PATH,
    )
    response.set_cookie(  # NOSONAR The client must read this CSRF token for double-submit.
        config.csrf_cookie_name,
        generate_csrf_token(session_id, config.signing_key),
        max_age=max_age,
        httponly=False,
        samesite=COOKIE_SAME_SITE,
        secure=secure,
        path=COOKIE_PATH,
    )


def clear_session_cookies(response: Response, config: WebAuthConfig) -> None:
    """Take both cookies back, so the browser stops carrying a dead session."""
    response.delete_cookie(config.session_cookie_name, path=COOKIE_PATH)
    response.delete_cookie(config.csrf_cookie_name, path=COOKIE_PATH)


def enforce_login_attempt_limits(
    attempts: LoginAttemptStore,
    *,
    ip_address: str,
    username: str,
    config: WebAuthConfig,
) -> None:
    """Refuse an attempt that has spent either failure budget.

    The lockout counts this account's failures over a long window wherever
    they came from; the rate limit counts the address on its own and the
    account over a short one, and each refusal names how long it stands.
    """
    lockout_failures = attempts.count_recent_failures(
        ip_address=ip_address,
        window_seconds=config.login_lockout_window_seconds,
        username=username,
    )
    if lockout_failures >= config.login_lockout_threshold:
        raise HTTPException(
            429,
            ACCOUNT_LOCKED_DETAIL,
            headers={RETRY_AFTER_HEADER: str(config.login_lockout_window_seconds)},
        )

    window = config.login_rate_window_seconds
    address_failures = attempts.count_recent_failures(
        ip_address=ip_address, window_seconds=window,
    )
    account_failures = attempts.count_recent_failures(
        ip_address=ip_address, window_seconds=window, username=username,
    )
    if (
        address_failures >= config.login_rate_limit
        or account_failures >= config.login_rate_limit
    ):
        raise HTTPException(
            429,
            TOO_MANY_LOGIN_ATTEMPTS_DETAIL,
            headers={RETRY_AFTER_HEADER: str(window)},
        )


def password_admits_account(password: str, user: UserRecord | None) -> bool:
    """Whether ``password`` signs ``user`` in, at the same cost when it does not.

    A username nobody holds is verified against a dummy hash and a deactivated
    account is judged only after that verification, so neither answers faster
    than a plain wrong password does.
    """
    password_matches = verify_password_constant_time(
        password, user.password_hash if user else None,
    )
    return user is not None and password_matches and user.is_active
