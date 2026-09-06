"""Shared arrangement for the webauth suites.

A plain builder rather than a `conftest.py`: pytest puts every test directory
on `sys.path`, so a second `conftest` module here would shadow the repository
one that the rest of the suite imports `TEST_SECRET` and its factories from.
"""

from __future__ import annotations

import re

from pydantic import SecretStr

from webauth.config import (
    MIN_SESSION_SECRET_CHARS,
    RateLimitKeyPrefixes,
    SessionKeyPrefixes,
    WebAuthConfig,
)
from webauth.proxies import TrustedProxies

TRUSTED_PROXY_NETWORK = "172.16.0.0/12"


def a_web_auth_config(**overrides: object) -> WebAuthConfig:
    """A complete configuration; a keyword replaces the field it names."""
    defaults = {
        "session_secret": SecretStr("s" * MIN_SESSION_SECRET_CHARS),
        "redis": object(),
        "trusted_proxies": TrustedProxies.parse(TRUSTED_PROXY_NETWORK),
        "session_key_prefixes": SessionKeyPrefixes(
            session="app:session", user_sessions="app:user_sessions",
        ),
        "rate_limit_key_prefixes": RateLimitKeyPrefixes(
            api="rl:ip", media="rl:ip-media", stream="rl:ip-stream",
        ),
        "allowed_hosts_exact": frozenset({"songmaker.example"}),
        "allowed_hosts_patterns": (re.compile(r"^[^:]+\.example(:\d+)?$"),),
        "session_max_age_seconds": 3600,
        "session_absolute_max_age_seconds": 86400,
        "login_rate_limit": 5,
        "login_lockout_threshold": 15,
        "login_lockout_window_seconds": 3600,
    }
    return WebAuthConfig(**{**defaults, **overrides})
