"""Database engine and session management."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.db.models import Base

log = logging.getLogger(__name__)

MIGRATIONS_DIR = str(Path(__file__).parent / "migrations")

DEFAULT_PG_POOL_SIZE = 5
DEFAULT_PG_MAX_OVERFLOW = 10

_DEFAULT_SQLITE_TIMEOUT = 30


def resolve_database_url() -> str:
    """Return DATABASE_URL from env. Raises RuntimeError if not set."""
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    raise RuntimeError(
        "DATABASE_URL environment variable is required. "
        "Set it to a PostgreSQL connection string (e.g. postgresql://user:pass@host/db)."
    )


def _run_migrations(url: str) -> None:
    """Run Alembic migrations, stamping existing databases that lack alembic_version."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", MIGRATIONS_DIR)
    cfg.set_main_option("sqlalchemy.url", url)

    engine = create_engine(url)
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    engine.dispose()

    has_app_tables = "albums" in table_names
    has_alembic = "alembic_version" in table_names

    if has_app_tables and not has_alembic:
        command.stamp(cfg, "head", purge=True)
        log.info("Stamped existing database at current migration head")
        return

    command.upgrade(cfg, "head")


def init_db(url: str) -> sessionmaker[Session]:
    """Create the PostgreSQL engine, run migrations, and return a session factory."""
    _run_migrations(url)

    engine = create_engine(
        url, echo=False,
        pool_size=DEFAULT_PG_POOL_SIZE,
        max_overflow=DEFAULT_PG_MAX_OVERFLOW,
        pool_pre_ping=True,
    )

    log.info("Database initialized: %s", url.split("@")[-1] if "@" in url else url)
    return sessionmaker(bind=engine)


# ── Test-only (SQLite) ───────────────────────────────────────────────


def _enable_sqlite_pragmas(engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def init_test_db(db_path: Path) -> sessionmaker[Session]:
    """Fast test-only database init using create_all() instead of Alembic."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path}"
    engine = create_engine(url, echo=False, connect_args={"timeout": _DEFAULT_SQLITE_TIMEOUT})
    _enable_sqlite_pragmas(engine)

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)
