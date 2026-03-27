"""Application context — single owner of all shared state."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker


@dataclass
class AppContext:
    db: sessionmaker[Session]
    output_dir: Path
    session_secret: bytes
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
