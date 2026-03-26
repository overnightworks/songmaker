"""Database engine and session management."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.db.models import Base

log = logging.getLogger(__name__)

MIGRATIONS_DIR = str(Path(__file__).parent / "migrations")


def _enable_sqlite_pragmas(engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _run_migrations(db_path: Path) -> None:
    """Run Alembic migrations, stamping existing databases that lack alembic_version."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", MIGRATIONS_DIR)
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    engine.dispose()

    has_app_tables = "albums" in table_names
    has_alembic = "alembic_version" in table_names

    if has_app_tables and not has_alembic:
        command.stamp(cfg, "head")
        log.info("Stamped existing database at current migration head")
        return

    command.upgrade(cfg, "head")


def init_db(db_path: Path) -> sessionmaker[Session]:
    """Create the database engine, run migrations, and return a session factory.

    Pure function — no global state. Each call creates a new engine.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path}"

    _run_migrations(db_path)

    engine = create_engine(url, echo=False, connect_args={"timeout": 30})
    _enable_sqlite_pragmas(engine)

    _restrict_permissions(db_path)

    log.info("Database initialized: %s (WAL mode)", db_path)
    return sessionmaker(bind=engine)


def init_test_db(db_path: Path) -> sessionmaker[Session]:
    """Fast test-only database init using create_all() instead of Alembic."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path}"
    engine = create_engine(url, echo=False, connect_args={"timeout": 30})
    _enable_sqlite_pragmas(engine)

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _restrict_permissions(db_path: Path) -> None:
    if db_path.exists():
        os.chmod(db_path, stat.S_IRUSR | stat.S_IWUSR)
    for suffix in ("-wal", "-shm"):
        wal_path = db_path.parent / (db_path.name + suffix)
        if wal_path.exists():
            os.chmod(wal_path, stat.S_IRUSR | stat.S_IWUSR)
