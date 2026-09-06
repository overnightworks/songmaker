"""The signed session cookie and the CSRF token bound to it."""

from __future__ import annotations

import hashlib
import hmac
from typing import Final

DEFAULT_SESSION_COOKIE_NAME: Final = "session_id"
DEFAULT_CSRF_COOKIE_NAME: Final = "csrf_token"
DEFAULT_CSRF_HEADER_NAME: Final = "x-csrf-token"


def sign_session_id(session_id: str, secret: bytes) -> str:
    """Return ``session_id.hmac_hex`` for use as a cookie value."""
    sig = hmac.new(secret, session_id.encode(), hashlib.sha256).hexdigest()
    return f"{session_id}.{sig}"


def verify_session_cookie(cookie_value: str, secret: bytes) -> str | None:
    """Verify the HMAC signature and return the raw session_id, or None."""
    if "." not in cookie_value:
        return None
    session_id, sig = cookie_value.rsplit(".", 1)
    if not session_id or not sig:
        return None
    expected = hmac.new(secret, session_id.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return session_id
    return None


def generate_csrf_token(session_id: str, secret: bytes) -> str:
    """Generate a CSRF token cryptographically bound to the session."""
    return hmac.new(secret, f"csrf:{session_id}".encode(), hashlib.sha256).hexdigest()


def verify_csrf_token(token: str, session_id: str, secret: bytes) -> bool:
    """Verify a CSRF token is valid for the given session."""
    expected = generate_csrf_token(session_id, secret)
    return hmac.compare_digest(token, expected)
