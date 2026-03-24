"""Tests for auth utilities — password hashing, session secret, constants."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from songmaker_cli.auth import (
    BCRYPT_ROUNDS,
    GENERATION_RATE_LIMIT_USER,
    LOGIN_RATE_LIMIT,
    MAX_QUEUE_DEPTH,
    MAX_USER_ACTIVE_JOBS,
    MIN_PASSWORD_LENGTH,
    MIN_USERNAME_LENGTH,
    RATE_LIMIT_WINDOW_SECONDS,
    ROLE_ADMIN,
    ROLE_USER,
    SCORING_RATE_LIMIT_USER,
    SESSION_MAX_AGE_SECONDS,
    get_session_secret,
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


def test_get_session_secret_missing() -> None:
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError, match="SESSION_SECRET not set"):
            get_session_secret()


def test_get_session_secret_present() -> None:
    with patch.dict(os.environ, {"SESSION_SECRET": "abc123"}):
        assert get_session_secret() == "abc123"


def test_get_session_secret_empty_string() -> None:
    with patch.dict(os.environ, {"SESSION_SECRET": ""}):
        with pytest.raises(RuntimeError, match="SESSION_SECRET not set"):
            get_session_secret()


def test_constants() -> None:
    assert BCRYPT_ROUNDS == 12
    assert ROLE_ADMIN == "admin"
    assert ROLE_USER == "user"
    assert MIN_USERNAME_LENGTH == 3
    assert MIN_PASSWORD_LENGTH == 8
    assert LOGIN_RATE_LIMIT == 5
    assert SESSION_MAX_AGE_SECONDS == 60 * 60 * 24 * 30
    assert GENERATION_RATE_LIMIT_USER == 3
    assert SCORING_RATE_LIMIT_USER == 10
    assert RATE_LIMIT_WINDOW_SECONDS == 3600
    assert MAX_QUEUE_DEPTH == 10
    assert MAX_USER_ACTIVE_JOBS == 1
