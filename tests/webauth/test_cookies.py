"""The signed session cookie and the CSRF token bound to it."""

from __future__ import annotations

from webauth.cookies import (
    DEFAULT_CSRF_COOKIE_NAME,
    DEFAULT_CSRF_HEADER_NAME,
    DEFAULT_SESSION_COOKIE_NAME,
    generate_csrf_token,
    sign_session_id,
    verify_csrf_token,
    verify_session_cookie,
)

_TEST_SECRET = b"a" * 64


def test_default_names_are_what_the_browser_already_carries() -> None:
    """A deployment that upgrades must not log everybody out, so the names
    the library defaults to are the ones already in people's browsers."""
    assert DEFAULT_SESSION_COOKIE_NAME == "session_id"
    assert DEFAULT_CSRF_COOKIE_NAME == "csrf_token"
    assert DEFAULT_CSRF_HEADER_NAME == "x-csrf-token"


def test_sign_and_verify_session() -> None:
    signed = sign_session_id("my-session-token", _TEST_SECRET)
    assert "." in signed
    assert verify_session_cookie(signed, _TEST_SECRET) == "my-session-token"


def test_verify_rejects_tampered_signature() -> None:
    signed = sign_session_id("my-session-token", _TEST_SECRET)
    tampered = signed[:-4] + "XXXX"
    assert verify_session_cookie(tampered, _TEST_SECRET) is None


def test_verify_rejects_no_dot() -> None:
    assert verify_session_cookie("no-dot-here", _TEST_SECRET) is None


def test_verify_rejects_empty_parts() -> None:
    assert verify_session_cookie(".abc", _TEST_SECRET) is None
    assert verify_session_cookie("abc.", _TEST_SECRET) is None


def test_verify_rejects_another_secret() -> None:
    signed = sign_session_id("my-session-token", _TEST_SECRET)
    assert verify_session_cookie(signed, b"b" * 64) is None


def test_generate_csrf_token_deterministic() -> None:
    t1 = generate_csrf_token("session-abc", _TEST_SECRET)
    t2 = generate_csrf_token("session-abc", _TEST_SECRET)
    assert t1 == t2


def test_generate_csrf_token_differs_per_session() -> None:
    t1 = generate_csrf_token("session-1", _TEST_SECRET)
    t2 = generate_csrf_token("session-2", _TEST_SECRET)
    assert t1 != t2


def test_verify_csrf_token_valid() -> None:
    token = generate_csrf_token("my-session", _TEST_SECRET)
    assert verify_csrf_token(token, "my-session", _TEST_SECRET) is True


def test_verify_csrf_token_wrong_session() -> None:
    token = generate_csrf_token("session-a", _TEST_SECRET)
    assert verify_csrf_token(token, "session-b", _TEST_SECRET) is False


def test_verify_csrf_token_forged() -> None:
    assert verify_csrf_token("forged-token", "session-a", _TEST_SECRET) is False
