"""Tests for auth utilities — password hashing, HMAC signing, password strength."""

from __future__ import annotations

from pathlib import Path

import pytest

from songmaker_cli.auth import (
    BCRYPT_ROUNDS,
    GENERATION_RATE_LIMIT_USER,
    LOGIN_LOCKOUT_THRESHOLD,
    LOGIN_LOCKOUT_WINDOW_SECONDS,
    LOGIN_RATE_LIMIT,
    MAX_QUEUE_DEPTH,
    MAX_USER_ACTIVE_JOBS,
    MIN_PASSWORD_LENGTH,
    RATE_LIMIT_WINDOW_SECONDS,
    ROLE_ADMIN,
    SCORING_RATE_LIMIT_USER,
    SESSION_ABSOLUTE_MAX_AGE_SECONDS,
    SESSION_MAX_AGE_SECONDS,
    check_password_strength,
    ensure_session_secret,
    generate_csrf_token,
    get_client_ip,
    hash_password,
    parse_trusted_proxies,
    sign_session_id,
    verify_csrf_token,
    verify_password,
    verify_session_cookie,
)

_TEST_SECRET = b"a" * 64


def test_hash_and_verify_password() -> None:
    hashed = hash_password("testpassword123")
    assert hashed != "testpassword123"
    assert verify_password("testpassword123", hashed)


def test_verify_wrong_password() -> None:
    hashed = hash_password("correct-password")
    assert not verify_password("wrong-password", hashed)


def test_hash_produces_different_hashes() -> None:
    h1 = hash_password("same-password")
    h2 = hash_password("same-password")
    assert h1 != h2


def test_constants() -> None:
    assert BCRYPT_ROUNDS == 12
    assert ROLE_ADMIN == "admin"
    assert MIN_PASSWORD_LENGTH == 8
    assert LOGIN_RATE_LIMIT == 5
    assert SESSION_MAX_AGE_SECONDS == 60 * 60 * 24 * 30
    assert SESSION_ABSOLUTE_MAX_AGE_SECONDS == 60 * 60 * 24 * 90
    assert GENERATION_RATE_LIMIT_USER == 3
    assert SCORING_RATE_LIMIT_USER == 10
    assert RATE_LIMIT_WINDOW_SECONDS == 3600
    assert MAX_QUEUE_DEPTH == 100
    assert MAX_USER_ACTIVE_JOBS == 10
    assert LOGIN_LOCKOUT_THRESHOLD == 15
    assert LOGIN_LOCKOUT_WINDOW_SECONDS == 3600


# -- HMAC session signing ---------------------------------------------------


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


def test_ensure_session_secret_generates_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    result = ensure_session_secret(tmp_path)
    assert len(result) >= 32
    secret_file = tmp_path / ".session_secret"
    assert secret_file.exists()
    assert secret_file.read_text().strip() == result


def test_ensure_session_secret_reads_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    secret_file = tmp_path / ".session_secret"
    secret_file.write_text("b" * 64)
    result = ensure_session_secret(tmp_path)
    assert result == "b" * 64


def test_ensure_session_secret_prefers_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SECRET", "c" * 64)
    result = ensure_session_secret(tmp_path)
    assert result == "c" * 64


# -- Password strength -------------------------------------------------------


def test_common_password_rejected() -> None:
    with pytest.raises(ValueError, match="too common"):
        check_password_strength("password")


def test_low_entropy_rejected() -> None:
    with pytest.raises(ValueError, match="unique characters"):
        check_password_strength("aaaaaaaa")


def test_strong_password_accepted() -> None:
    assert check_password_strength("s3cur3P@ss!") == "s3cur3P@ss!"


# -- CSRF token binding ------------------------------------------------------


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


def test_none_password_passes() -> None:
    assert check_password_strength(None) is None


# -- Trusted proxies (parse_trusted_proxies) ---------------------------------


def test_parse_trusted_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.1, 10.0.0.2")
    result = parse_trusted_proxies()
    assert result == frozenset({"10.0.0.1", "10.0.0.2"})


def test_parse_trusted_proxies_empty_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    result = parse_trusted_proxies()
    assert result == frozenset()


# -- get_client_ip -----------------------------------------------------------


def test_get_client_ip_no_trusted_proxies() -> None:
    assert get_client_ip("1.2.3.4", "5.6.7.8, 9.10.11.12", frozenset()) == "1.2.3.4"
