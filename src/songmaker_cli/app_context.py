"""Application context — single owner of all shared state."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

if TYPE_CHECKING:
    from redis import Redis


@dataclass
class AppContext:
    db: sessionmaker[Session]
    audio_dir: Path
    data_dir: Path
    session_secret: bytes
    redis: Redis
    trusted_proxies: frozenset[str] = field(default_factory=frozenset)
    allowed_hosts_exact: frozenset[str] = field(default_factory=frozenset)
    allowed_hosts_patterns: list[re.Pattern[str]] = field(default_factory=list)


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
