"""Database engine and session management."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
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
    _migrate_schema(engine)
    _session_factory = sessionmaker(bind=engine)

    log.info("Database initialized: %s", db_path)
    return _session_factory


def _migrate_schema(engine) -> None:
    """Add columns that may be missing from older databases."""
    inspector = inspect(engine)

    gen_columns = {c["name"] for c in inspector.get_columns("generations")}
    if "is_picked" not in gen_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE generations ADD COLUMN is_picked BOOLEAN DEFAULT 0"))
        log.info("Migration: added is_picked column to generations")

    ver_columns = {c["name"] for c in inspector.get_columns("versions")}
    if "generation_params" not in ver_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE versions ADD COLUMN generation_params JSON"))
        log.info("Migration: added generation_params column to versions")


def get_session_factory() -> sessionmaker[Session]:
    """Get the current session factory. Raises if init_db hasn't been called."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    return _session_factory


def reset_engine() -> None:
    """Reset the global session factory (for testing)."""
    global _session_factory
    _session_factory = None
