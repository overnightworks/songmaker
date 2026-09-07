"""Application context — single owner of all shared state."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Request
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker
from webauth.config import (
    RateLimitKeyPrefixes,
    SessionKeyPrefixes,
    WebAuthConfig,
)
from webauth.proxies import TrustedProxies

from songmaker_cli.constants import (
    HTTP_MAX_USER_AGENT_LENGTH,
    REDIS_RL_IP_MEDIA_PREFIX,
    REDIS_RL_IP_PREFIX,
    REDIS_RL_IP_STREAM_PREFIX,
    REDIS_SESSION_PREFIX,
    REDIS_USER_SESSIONS_PREFIX,
    ROLE_ADMIN,
)

if TYPE_CHECKING:
    from redis import Redis

    from songmaker_cli.settings import Settings


@dataclass
class AppContext:
    db: sessionmaker[Session]
    audio_dir: Path
    data_dir: Path
    signing_key: bytes
    redis: Redis
    trusted_proxies: TrustedProxies = field(default_factory=TrustedProxies)
    allowed_hosts_exact: frozenset[str] = field(default_factory=frozenset)
    allowed_hosts_patterns: list[re.Pattern[str]] = field(default_factory=list)


def parse_trusted_proxies(settings: Settings) -> TrustedProxies:
    """Read TRUSTED_PROXIES. Raises at startup on an unparsable entry."""
    try:
        return TrustedProxies.parse(settings.trusted_proxies)
    except ValueError as exc:
        raise ValueError(f"TRUSTED_PROXIES is invalid: {exc}") from exc


def build_web_auth_config(ctx: AppContext, settings: Settings) -> WebAuthConfig:
    """The auth library's view of this deployment, assembled from songmaker's."""
    return WebAuthConfig(
        session_secret=SecretStr(ctx.signing_key.decode()),
        redis=ctx.redis,
        trusted_proxies=ctx.trusted_proxies,
        session_key_prefixes=SessionKeyPrefixes(
            session=REDIS_SESSION_PREFIX,
            user_sessions=REDIS_USER_SESSIONS_PREFIX,
        ),
        rate_limit_key_prefixes=RateLimitKeyPrefixes(
            api=REDIS_RL_IP_PREFIX,
            media=REDIS_RL_IP_MEDIA_PREFIX,
            stream=REDIS_RL_IP_STREAM_PREFIX,
        ),
        allowed_hosts_exact=ctx.allowed_hosts_exact,
        allowed_hosts_patterns=tuple(ctx.allowed_hosts_patterns),
        session_max_age_seconds=settings.session_max_age_seconds,
        session_absolute_max_age_seconds=settings.session_absolute_max_age_seconds,
        max_user_agent_chars=HTTP_MAX_USER_AGENT_LENGTH,
        login_rate_limit=settings.login_rate_limit,
        login_lockout_threshold=settings.login_lockout_threshold,
        login_lockout_window_seconds=settings.login_lockout_window_seconds,
        admin_role=ROLE_ADMIN,
    )


def get_app_context(request: Request) -> AppContext:
    """FastAPI dependency: extract AppContext from app state."""
    return request.app.state.ctx


def get_db_session(request: Request) -> Session:  # type: ignore[misc]
    """FastAPI dependency: yield a SQLAlchemy session from AppContext."""
    ctx: AppContext = request.app.state.ctx
    session = ctx.db()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
