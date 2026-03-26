"""Authentication utilities — password hashing, session signing, constants."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

import bcrypt

BCRYPT_ROUNDS = 12
TRUSTED_PROXIES: frozenset[str] = frozenset(
    p.strip() for p in os.environ.get("TRUSTED_PROXIES", "").split(",") if p.strip()
)


def get_client_ip(client_host: str, forwarded_for: str | None) -> str:
    """Extract the real client IP, using rightmost untrusted XFF entry."""
    if TRUSTED_PROXIES and client_host in TRUSTED_PROXIES and forwarded_for:
        ips = [ip.strip() for ip in forwarded_for.split(",")]
        for ip in reversed(ips):
            if ip not in TRUSTED_PROXIES:
                return ip
    return client_host
SESSION_MAX_AGE_SECONDS = int(os.environ.get("SESSION_MAX_AGE", 60 * 60 * 24 * 30))
SESSION_ABSOLUTE_MAX_AGE_SECONDS = int(
    os.environ.get("SESSION_ABSOLUTE_MAX_AGE", 60 * 60 * 24 * 90),
)
LOGIN_RATE_LIMIT = int(os.environ.get("LOGIN_RATE_LIMIT", 5))
LOGIN_RATE_WINDOW_SECONDS = 300

ROLE_ADMIN = "admin"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "x-csrf-token"

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


# ── Password strength ──────────────────────────────────────────────

_COMMON_PASSWORDS = frozenset({
    "password", "12345678", "123456789", "1234567890", "qwerty123",
    "password1", "iloveyou", "sunshine1", "princess1", "football1",
    "trustno1", "letmein1", "baseball1", "abc12345", "monkey123",
    "dragon12", "michael1", "jennifer1", "superman1", "shadow12",
    "password123", "admin123", "welcome1", "changeme1", "passw0rd",
    "p@ssw0rd", "p@ssword", "abcd1234", "1q2w3e4r", "qwer1234",
    "asdfghjk", "zxcvbnm1", "11111111", "00000000", "12341234",
    "abcdefgh", "87654321", "master12", "access14", "charlie1",
    "qwerty12", "iloveu12", "starwars", "whatever", "computer",
    "corvette", "maverick", "steelers",
    "admin1234", "welcome123", "password12", "letmein12", "master123",
    "login123", "welcome12", "mustang1", "jordan23", "buster12",
    "ranger12", "batman12", "thomas12", "robert12", "soccer12",
    "hockey12", "hunter12", "george12", "andrew12", "harley12",
    "daniel12", "matthew1", "jessica1", "william1", "anthony1",
    "summer12", "winter12", "spring12", "autumn12", "january1",
    "february", "december", "saturday", "thursday", "midnight",
    "sunshine", "princess", "football", "baseball", "trustno12",
    "qwerty1234", "asdf1234", "zxcv1234", "q1w2e3r4", "1234qwer",
    "pass1234", "test1234", "temp1234", "user1234", "guest1234",
    "default1", "system12", "server12", "network1", "internet",
    "security", "password1234", "admin12345", "root1234", "toor1234",
    "samsung1", "ferrari1", "porsche1", "mercedes", "corvett1",
    "elephant", "giraffe1", "dolphins", "predator", "scorpion",
    "spiderman", "ironman1", "avengers", "deadpool", "thanos12",
    "iloveyou1", "iloveyou2", "loveyou1", "mylove12", "forever1",
    "diamond1", "crystal1", "rainbow1", "butterfly", "angelica",
    "carolina", "virginia", "colorado", "portland", "california",
    "newyork1", "london12", "paris123", "tokyo123", "berlin12",
    "samsung123", "apple123", "google12", "amazon12", "facebook",
    "twitter1", "youtube1", "spotify1", "netflix1", "linkedin",
    "sunshine123", "chocolate", "strawberry", "blueberry", "mountain",
    "password!", "p@ss1234", "p@$$w0rd", "pa$$word", "pa55word",
    "trustme1", "believe1", "freedom1", "justice1", "liberty1",
    "american", "patriots", "yankees1", "lakers12", "cowboys1",
    "packers1", "arsenal1", "chelsea1", "liverpool", "barcelona",
    "realmadrid", "juventus", "manchester",
    "summer2024", "summer2025", "summer2026", "winter2024", "winter2025",
    "spring2024", "spring2025", "spring2026", "welcome2024", "welcome2025",
    "january2024", "january2025", "january2026",
    "qwertyui", "asdfghjkl", "zxcvbnm12", "1qaz2wsx", "2wsx3edc",
    "qazwsxed", "q1w2e3r4t5", "1q2w3e4r5t",
})

MIN_UNIQUE_CHARS = 4


def check_password_strength(cls_or_value: str, *_args: object) -> str:
    """Pydantic-compatible validator: reject common and low-entropy passwords.

    Works both as a standalone function and as a Pydantic field_validator
    (which passes `cls` as first arg in classmethod mode, but we accept
    the value in either position via the *_args fallback).
    """
    password = cls_or_value
    if password is None:
        return password
    if password.lower() in _COMMON_PASSWORDS:
        raise ValueError("Password is too common — choose something less predictable")
    if len(set(password)) < MIN_UNIQUE_CHARS:
        raise ValueError(
            f"Password must contain at least {MIN_UNIQUE_CHARS} unique characters"
        )
    return password


# ── HMAC session signing ───────────────────────────────────────────

_session_secret: str | None = None


def _get_session_secret() -> str:
    global _session_secret
    if _session_secret is not None:
        return _session_secret
    secret = os.environ.get("SESSION_SECRET", "")
    if not secret or len(secret) < 32:
        raise RuntimeError(
            "SESSION_SECRET not set. The server generates one automatically at startup."
        )
    _session_secret = secret
    return secret


def reset_session_secret() -> None:
    """Clear cached session secret (for testing)."""
    global _session_secret
    _session_secret = None


def ensure_session_secret(output_dir_path: str | os.PathLike) -> str:
    """Generate or load a persistent session signing secret.

    Called once at server startup. Stores the secret in
    ``<output_dir>/.session_secret`` with 0600 permissions.
    """
    from pathlib import Path

    secret = os.environ.get("SESSION_SECRET")
    if secret and len(secret) >= 32:
        os.environ["SESSION_SECRET"] = secret
        return secret

    secret_file = Path(output_dir_path) / ".session_secret"
    if secret_file.exists():
        secret = secret_file.read_text().strip()
        if len(secret) >= 32:
            os.environ["SESSION_SECRET"] = secret
            return secret

    secret = secrets.token_hex(32)
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text(secret)
    os.chmod(secret_file, 0o600)
    os.environ["SESSION_SECRET"] = secret
    return secret


def sign_session_id(session_id: str) -> str:
    """Return ``session_id.hmac_hex`` for use as a cookie value."""
    secret = _get_session_secret()
    sig = hmac.new(secret.encode(), session_id.encode(), hashlib.sha256).hexdigest()
    return f"{session_id}.{sig}"


def verify_session_cookie(cookie_value: str) -> str | None:
    """Verify the HMAC signature and return the raw session_id, or None."""
    if "." not in cookie_value:
        return None
    session_id, sig = cookie_value.rsplit(".", 1)
    if not session_id or not sig:
        return None
    secret = _get_session_secret()
    expected = hmac.new(secret.encode(), session_id.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return session_id
    return None


def generate_csrf_token(session_id: str) -> str:
    """Generate a CSRF token cryptographically bound to the session."""
    secret = _get_session_secret()
    return hmac.new(secret.encode(), f"csrf:{session_id}".encode(), hashlib.sha256).hexdigest()


def verify_csrf_token(token: str, session_id: str) -> bool:
    """Verify a CSRF token is valid for the given session."""
    expected = generate_csrf_token(session_id)
    return hmac.compare_digest(token, expected)
