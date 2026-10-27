"""Application context — single owner of all shared state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Request
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker
from webauth.config import SessionLifetime, WebAuthConfig
from webauth.proxies import TrustedProxies
from webauth.rate_limit import RedisRateLimitBackend

from songmaker_cli.constants import REDIS_RL_IP_PREFIX, ROLE_ADMIN

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


def parse_trusted_proxies(settings: Settings) -> TrustedProxies:
    """Read TRUSTED_PROXIES. Raises at startup on an unparsable entry."""
    try:
        return TrustedProxies.parse(settings.trusted_proxies)
    except ValueError as exc:
        raise ValueError(f"TRUSTED_PROXIES is invalid: {exc}") from exc


def allowed_hosts(settings: Settings) -> tuple[str, ...]:
    """ALLOWED_HOSTS entries: exact host names, the one list behind both the Host
    check and the Origin allowlist. A `*` entry raises at startup."""
    hosts = tuple(entry.strip() for entry in settings.allowed_hosts.split(",") if entry.strip())
    for host in hosts:
        if "*" in host:
            raise ValueError(f"ALLOWED_HOSTS takes exact host names only, not {host!r}")
    return hosts


def build_web_auth_config(ctx: AppContext, settings: Settings) -> WebAuthConfig:
    """The auth library's view of this deployment, assembled from songmaker's."""
    return WebAuthConfig(
        session_secret=SecretStr(ctx.signing_key.decode()),
        rate_limits=RedisRateLimitBackend(ctx.redis, key_prefix=REDIS_RL_IP_PREFIX),
        trusted_proxies=ctx.trusted_proxies,
        allowed_hosts_exact=frozenset(allowed_hosts(settings)),
        session_lifetime=SessionLifetime(
            idle_seconds=settings.session_idle_seconds,
            absolute_max_age_seconds=settings.session_absolute_max_age_seconds,
        ),
        admin_role=ROLE_ADMIN,
        cookie_secure=settings.cookie_secure,
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
