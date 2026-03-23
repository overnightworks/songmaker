"""Database engine and session management."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.db.models import Base

log = logging.getLogger(__name__)

_session_factory: sessionmaker[Session] | None = None


def init_db(db_path: Path) -> sessionmaker[Session]:
    """Create the database engine, create tables, and return a session factory.

    Idempotent — calling multiple times with the same path returns the same factory.
    """
    global _session_factory
    if _session_factory is not None:
        return _session_factory

    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path}"
    engine = create_engine(url, echo=False)
    Base.metadata.create_all(engine)
    _session_factory = sessionmaker(bind=engine)

    log.info("Database initialized: %s", db_path)
    return _session_factory


def get_session_factory() -> sessionmaker[Session]:
    """Get the current session factory. Raises if init_db hasn't been called."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    return _session_factory


def reset_engine() -> None:
    """Reset the global session factory (for testing)."""
    global _session_factory
    _session_factory = None
