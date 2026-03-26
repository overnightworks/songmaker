"""Tests for auth utilities — password hashing, HMAC signing, password strength."""

from __future__ import annotations

import os
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
    get_trusted_proxies,
    hash_password,
    reset_session_secret,
    reset_trusted_proxies,
    sign_session_id,
    verify_csrf_token,
    verify_password,
    verify_session_cookie,
)


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
    assert MAX_QUEUE_DEPTH == 10
    assert MAX_USER_ACTIVE_JOBS == 1
    assert LOGIN_LOCKOUT_THRESHOLD == 15
    assert LOGIN_LOCKOUT_WINDOW_SECONDS == 3600


# ── HMAC session signing ───────────────────────────────────────────


def test_sign_and_verify_session() -> None:
    signed = sign_session_id("my-session-token")
    assert "." in signed
    assert verify_session_cookie(signed) == "my-session-token"


def test_verify_rejects_tampered_signature() -> None:
    signed = sign_session_id("my-session-token")
    tampered = signed[:-4] + "XXXX"
    assert verify_session_cookie(tampered) is None


def test_verify_rejects_no_dot() -> None:
    assert verify_session_cookie("no-dot-here") is None


def test_verify_rejects_empty_parts() -> None:
    assert verify_session_cookie(".abc") is None
    assert verify_session_cookie("abc.") is None


def test_ensure_session_secret_generates_file(tmp_path: Path) -> None:
    reset_session_secret()
    old = os.environ.pop("SESSION_SECRET", None)
    try:
        result = ensure_session_secret(tmp_path)
        assert len(result) >= 32
        assert os.environ["SESSION_SECRET"] == result
        secret_file = tmp_path / ".session_secret"
        assert secret_file.exists()
        assert secret_file.read_text().strip() == result
    finally:
        if old:
            os.environ["SESSION_SECRET"] = old
        reset_session_secret()


def test_ensure_session_secret_reads_existing_file(tmp_path: Path) -> None:
    reset_session_secret()
    old = os.environ.pop("SESSION_SECRET", None)
    try:
        secret_file = tmp_path / ".session_secret"
        secret_file.write_text("b" * 64)
        result = ensure_session_secret(tmp_path)
        assert result == "b" * 64
    finally:
        if old:
            os.environ["SESSION_SECRET"] = old
        reset_session_secret()


def test_ensure_session_secret_prefers_env_var(tmp_path: Path) -> None:
    reset_session_secret()
    old = os.environ.get("SESSION_SECRET")
    try:
        os.environ["SESSION_SECRET"] = "c" * 64
        result = ensure_session_secret(tmp_path)
        assert result == "c" * 64
    finally:
        if old:
            os.environ["SESSION_SECRET"] = old
        else:
            os.environ.pop("SESSION_SECRET", None)
        reset_session_secret()


# ── Password strength ──────────────────────────────────────────────


def test_common_password_rejected() -> None:
    with pytest.raises(ValueError, match="too common"):
        check_password_strength("password")


def test_low_entropy_rejected() -> None:
    with pytest.raises(ValueError, match="unique characters"):
        check_password_strength("aaaaaaaa")


def test_strong_password_accepted() -> None:
    assert check_password_strength("s3cur3P@ss!") == "s3cur3P@ss!"


# ── CSRF token binding ────────────────────────────────────────────


def test_generate_csrf_token_deterministic() -> None:
    t1 = generate_csrf_token("session-abc")
    t2 = generate_csrf_token("session-abc")
    assert t1 == t2


def test_generate_csrf_token_differs_per_session() -> None:
    t1 = generate_csrf_token("session-1")
    t2 = generate_csrf_token("session-2")
    assert t1 != t2


def test_verify_csrf_token_valid() -> None:
    token = generate_csrf_token("my-session")
    assert verify_csrf_token(token, "my-session") is True


def test_verify_csrf_token_wrong_session() -> None:
    token = generate_csrf_token("session-a")
    assert verify_csrf_token(token, "session-b") is False


def test_verify_csrf_token_forged() -> None:
    assert verify_csrf_token("forged-token", "session-a") is False


def test_get_session_secret_raises_without_env() -> None:
    reset_session_secret()
    old = os.environ.pop("SESSION_SECRET", None)
    try:
        with pytest.raises(RuntimeError, match="SESSION_SECRET not set"):
            generate_csrf_token("anything")
    finally:
        if old:
            os.environ["SESSION_SECRET"] = old
        reset_session_secret()


def test_none_password_passes() -> None:
    assert check_password_strength(None) is None


# ── Trusted proxies (lazy) ───────────────────────────────────────


def test_get_trusted_proxies_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_trusted_proxies()
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.1, 10.0.0.2")
    try:
        result = get_trusted_proxies()
        assert result == frozenset({"10.0.0.1", "10.0.0.2"})
    finally:
        reset_trusted_proxies()


def test_get_trusted_proxies_empty_default() -> None:
    reset_trusted_proxies()
    old = os.environ.pop("TRUSTED_PROXIES", None)
    try:
        result = get_trusted_proxies()
        assert result == frozenset()
    finally:
        if old is not None:
            os.environ["TRUSTED_PROXIES"] = old
        reset_trusted_proxies()
