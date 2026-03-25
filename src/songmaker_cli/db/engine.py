"""Database engine and session management."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.db.models import Base

log = logging.getLogger(__name__)

_session_factory: sessionmaker[Session] | None = None
_db_path: Path | None = None


def init_db(db_path: Path) -> sessionmaker[Session]:
    """Create the database engine, create tables, and return a session factory.

    Idempotent — calling with the same path returns the cached factory.
    Raises if called with a different path (use reset_engine() first).
    """
    global _session_factory, _db_path
    if _session_factory is not None:
        if _db_path is not None and _db_path.resolve() != db_path.resolve():
            raise RuntimeError(
                f"Database already initialized at {_db_path}, "
                f"cannot reinitialize at {db_path}. Call reset_engine() first."
            )
        return _session_factory

    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path}"
    engine = create_engine(url, echo=False)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)

    if db_path.exists():
        os.chmod(db_path, stat.S_IRUSR | stat.S_IWUSR)
    for suffix in ("-wal", "-shm"):
        wal_path = db_path.parent / (db_path.name + suffix)
        if wal_path.exists():
            os.chmod(wal_path, stat.S_IRUSR | stat.S_IWUSR)

    _session_factory = sessionmaker(bind=engine)
    _db_path = db_path

    log.info("Database initialized: %s (WAL mode)", db_path)
    return _session_factory


def get_session_factory() -> sessionmaker[Session]:
    """Get the current session factory. Raises if init_db hasn't been called."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    return _session_factory


def reset_engine() -> None:
    """Reset the global session factory (for testing)."""
    global _session_factory, _db_path
    _session_factory = None
    _db_path = None


def get_db_session() -> Session:  # type: ignore[misc]
    """FastAPI dependency that yields a SQLAlchemy session with rollback on error."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
