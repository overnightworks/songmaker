"""Authentication utilities — password hashing, session config, constants."""

from __future__ import annotations

import os

import bcrypt

BCRYPT_ROUNDS = 12
SESSION_MAX_AGE_SECONDS = int(os.environ.get("SESSION_MAX_AGE", 60 * 60 * 24 * 30))
LOGIN_RATE_LIMIT = int(os.environ.get("LOGIN_RATE_LIMIT", 5))
LOGIN_RATE_WINDOW_SECONDS = 300

ROLE_ADMIN = "admin"
ROLE_USER = "user"

MIN_USERNAME_LENGTH = 3
MIN_PASSWORD_LENGTH = 8

GENERATION_RATE_LIMIT_USER = int(os.environ.get("GENERATION_RATE_LIMIT_USER", 3))
SCORING_RATE_LIMIT_USER = int(os.environ.get("SCORING_RATE_LIMIT_USER", 10))
RATE_LIMIT_WINDOW_SECONDS = 3600
MAX_QUEUE_DEPTH = int(os.environ.get("MAX_QUEUE_DEPTH", 10))
MAX_USER_ACTIVE_JOBS = 1


def get_session_secret() -> str:
    secret = os.environ.get("SESSION_SECRET", "")
    if not secret:
        msg = (
            "SESSION_SECRET not set. "
            "Generate one with: openssl rand -hex 32\n"
            "Add to .server.env: SESSION_SECRET=<value>"
        )
        raise RuntimeError(msg)
    return secret


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())
