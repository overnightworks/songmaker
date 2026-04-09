"""Authentication utilities — password hashing, session signing, constants."""

from __future__ import annotations

import hashlib
import hmac
import os

import bcrypt

from songmaker_cli.settings import get_settings

BCRYPT_ROUNDS = 12


def parse_trusted_proxies() -> frozenset[str]:
    """Parse trusted-proxies CSV from Settings. Returns a frozenset of proxy IPs."""
    raw = get_settings().trusted_proxies
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def get_client_ip(
    client_host: str, forwarded_for: str | None, trusted_proxies: frozenset[str],
) -> str:
    """Extract the real client IP, using rightmost untrusted XFF entry."""
    if trusted_proxies and client_host in trusted_proxies and forwarded_for:
        ips = [ip.strip() for ip in forwarded_for.split(",")]
        for ip in reversed(ips):
            if ip not in trusted_proxies:
                return ip
    return client_host


LOGIN_RATE_WINDOW_SECONDS = 300
RATE_LIMIT_WINDOW_SECONDS = 3600

ROLE_ADMIN = "admin"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "x-csrf-token"

MIN_PASSWORD_LENGTH = 8


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


def ensure_session_secret(_output_dir_path: str | os.PathLike) -> str:
    """Return the validated session signing secret from Settings.

    Settings.session_secret is required (W1 contract). ``_output_dir_path``
    is kept for call-site compatibility — the previous file-based fallback
    is gone now that secrets must come from .env.
    """
    secret = get_settings().session_secret.get_secret_value()
    if len(secret) < 32:
        raise RuntimeError(
            "SESSION_SECRET is too short — must be at least 32 characters",
        )
    return secret


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
