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


def init_db(db_path: Path) -> sessionmaker[Session]:
    """Create the database engine, create tables, and return a session factory.

    Pure function — no global state. Each call creates a new engine.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path}"
    engine = create_engine(url, echo=False, connect_args={"timeout": 30})

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

    log.info("Database initialized: %s (WAL mode)", db_path)
    return sessionmaker(bind=engine)
