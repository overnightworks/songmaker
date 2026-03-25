"""Tests for auth utilities — password hashing, constants."""

from __future__ import annotations

from songmaker_cli.auth import (
    BCRYPT_ROUNDS,
    GENERATION_RATE_LIMIT_USER,
    LOGIN_RATE_LIMIT,
    MAX_QUEUE_DEPTH,
    MAX_USER_ACTIVE_JOBS,
    MIN_PASSWORD_LENGTH,
    RATE_LIMIT_WINDOW_SECONDS,
    ROLE_ADMIN,
    SCORING_RATE_LIMIT_USER,
    SESSION_ABSOLUTE_MAX_AGE_SECONDS,
    SESSION_MAX_AGE_SECONDS,
    hash_password,
    verify_password,
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
