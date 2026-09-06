"""Transitional re-export of the auth utilities that now live in `webauth`.

Deleted once the middleware and the auth router move to the library (#825,
ruling k); until then this module keeps the existing importers working. New
code imports from `webauth` directly.
"""

from __future__ import annotations

from typing import Final

from webauth.cookies import (
    DEFAULT_CSRF_COOKIE_NAME,
    DEFAULT_CSRF_HEADER_NAME,
    generate_csrf_token,
    sign_session_id,
    verify_csrf_token,
    verify_session_cookie,
)
from webauth.passwords import (
    BCRYPT_ROUNDS,
    MIN_PASSWORD_LENGTH,
    MIN_UNIQUE_CHARS,
    check_password_strength,
    hash_password,
    verify_password,
    verify_password_constant_time,
)
from webauth.proxies import (
    MAX_ADDRESS_CHARS,
    MAX_FORWARDED_FOR_HOPS,
    TrustedProxies,
    get_client_ip,
    request_is_https,
    resolve_client_ip,
)

CSRF_COOKIE: Final = DEFAULT_CSRF_COOKIE_NAME
CSRF_HEADER: Final = DEFAULT_CSRF_HEADER_NAME

RATE_LIMIT_WINDOW_SECONDS: Final = 3600

ROLE_ADMIN: Final = "admin"

__all__ = [
    "BCRYPT_ROUNDS",
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "MAX_ADDRESS_CHARS",
    "MAX_FORWARDED_FOR_HOPS",
    "MIN_PASSWORD_LENGTH",
    "MIN_UNIQUE_CHARS",
    "RATE_LIMIT_WINDOW_SECONDS",
    "ROLE_ADMIN",
    "TrustedProxies",
    "check_password_strength",
    "generate_csrf_token",
    "get_client_ip",
    "hash_password",
    "request_is_https",
    "resolve_client_ip",
    "sign_session_id",
    "verify_csrf_token",
    "verify_password",
    "verify_password_constant_time",
    "verify_session_cookie",
]
