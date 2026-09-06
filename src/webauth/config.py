"""The deployment facts the auth machinery reads, supplied by the host application.

The library decides nothing about its own deployment: the application builds
one `WebAuthConfig` at startup and installs it on the ASGI application, and
every reader below takes it from the request. Nothing here reaches for an
environment variable, a settings singleton, or the application's own context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from starlette.requests import Request

from webauth.cookies import (
    DEFAULT_CSRF_COOKIE_NAME,
    DEFAULT_CSRF_HEADER_NAME,
    DEFAULT_SESSION_COOKIE_NAME,
)

if TYPE_CHECKING:
    import re

    from pydantic import SecretStr
    from redis import Redis
    from starlette.applications import Starlette

    from webauth.proxies import TrustedProxies

MIN_SESSION_SECRET_CHARS: Final = 32
DEFAULT_LOGIN_RATE_WINDOW_SECONDS: Final = 300
DEFAULT_ADMIN_ROLE: Final = "admin"
DEFAULT_USER_ROLE: Final = "user"

WEB_AUTH_STATE_ATTRIBUTE: Final = "webauth"


@dataclass(frozen=True)
class SessionKeyPrefixes:
    """Where the session cache keeps its two kinds of Redis key."""

    session: str
    user_sessions: str


@dataclass(frozen=True)
class RateLimitKeyPrefixes:
    """One Redis key prefix per per-IP budget, so no budget starves another."""

    api: str
    media: str
    stream: str


@dataclass(frozen=True)
class WebAuthConfig:
    session_secret: SecretStr
    redis: Redis
    trusted_proxies: TrustedProxies
    session_key_prefixes: SessionKeyPrefixes
    rate_limit_key_prefixes: RateLimitKeyPrefixes
    allowed_hosts_exact: frozenset[str]
    allowed_hosts_patterns: tuple[re.Pattern[str], ...]
    session_max_age_seconds: int
    session_absolute_max_age_seconds: int
    login_rate_limit: int
    login_lockout_threshold: int
    login_lockout_window_seconds: int
    login_rate_window_seconds: int = DEFAULT_LOGIN_RATE_WINDOW_SECONDS
    session_cookie_name: str = DEFAULT_SESSION_COOKIE_NAME
    csrf_cookie_name: str = DEFAULT_CSRF_COOKIE_NAME
    csrf_header_name: str = DEFAULT_CSRF_HEADER_NAME
    admin_role: str = DEFAULT_ADMIN_ROLE
    user_role: str = DEFAULT_USER_ROLE

    def __post_init__(self) -> None:
        if len(self.session_secret.get_secret_value()) < MIN_SESSION_SECRET_CHARS:
            raise ValueError(
                "The session secret is too short — it signs every session cookie and "
                f"must be at least {MIN_SESSION_SECRET_CHARS} characters.",
            )

    @property
    def signing_key(self) -> bytes:
        """The secret in the form the cookie and CSRF signatures take."""
        return self.session_secret.get_secret_value().encode()


def install_web_auth_config(app: Starlette, config: WebAuthConfig) -> None:
    """Publish ``config`` on ``app`` so every request can reach it."""
    setattr(app.state, WEB_AUTH_STATE_ATTRIBUTE, config)


def installed_web_auth_config(app: Starlette) -> WebAuthConfig:
    """The configuration ``app`` was started with."""
    config = getattr(app.state, WEB_AUTH_STATE_ATTRIBUTE, None)
    if config is None:
        raise RuntimeError(
            "This application serves auth-protected requests without a "
            "WebAuthConfig: call install_web_auth_config() while it starts up.",
        )
    return config


def web_auth_config(request: Request) -> WebAuthConfig:
    """The configuration installed on the application serving ``request``."""
    return installed_web_auth_config(request.app)
