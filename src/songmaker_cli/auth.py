"""Authentication utilities — password hashing, session config, constants."""

from __future__ import annotations

import os

import bcrypt

BCRYPT_ROUNDS = 12
SESSION_MAX_AGE_SECONDS = int(os.environ.get("SESSION_MAX_AGE", 60 * 60 * 24 * 30))
SESSION_ABSOLUTE_MAX_AGE_SECONDS = int(
    os.environ.get("SESSION_ABSOLUTE_MAX_AGE", 60 * 60 * 24 * 90),
)
LOGIN_RATE_LIMIT = int(os.environ.get("LOGIN_RATE_LIMIT", 5))
LOGIN_RATE_WINDOW_SECONDS = 300

ROLE_ADMIN = "admin"

MIN_PASSWORD_LENGTH = 8

GENERATION_RATE_LIMIT_USER = int(os.environ.get("GENERATION_RATE_LIMIT_USER", 3))
GENERATION_RATE_LIMIT_ADMIN = int(os.environ.get("GENERATION_RATE_LIMIT_ADMIN", 30))
SCORING_RATE_LIMIT_USER = int(os.environ.get("SCORING_RATE_LIMIT_USER", 10))
SCORING_RATE_LIMIT_ADMIN = int(os.environ.get("SCORING_RATE_LIMIT_ADMIN", 100))
CHAT_RATE_LIMIT_USER = int(os.environ.get("CHAT_RATE_LIMIT_USER", 30))
CHAT_RATE_LIMIT_ADMIN = int(os.environ.get("CHAT_RATE_LIMIT_ADMIN", 300))
RATE_LIMIT_WINDOW_SECONDS = 3600
MAX_QUEUE_DEPTH = int(os.environ.get("MAX_QUEUE_DEPTH", 10))
MAX_USER_ACTIVE_JOBS = 1


_DUMMY_HASH = bcrypt.hashpw(b"dummy", bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def verify_password_constant_time(password: str, password_hash: str | None) -> bool:
    """Verify password, using a dummy hash if None to prevent timing oracle."""
    return bcrypt.checkpw(password.encode(), (password_hash or _DUMMY_HASH).encode())
