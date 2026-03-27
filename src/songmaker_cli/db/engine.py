"""Database engine and session management."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.db.models import Base

log = logging.getLogger(__name__)

MIGRATIONS_DIR = str(Path(__file__).parent / "migrations")

DEFAULT_SQLITE_TIMEOUT = 30
DEFAULT_PG_POOL_SIZE = 5
DEFAULT_PG_MAX_OVERFLOW = 10


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _enable_sqlite_pragmas(engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


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
        command.stamp(cfg, "head")
        log.info("Stamped existing database at current migration head")
        return

    command.upgrade(cfg, "head")


def _build_engine_kwargs(url: str) -> dict[str, Any]:
    if _is_sqlite(url):
        return {"connect_args": {"timeout": DEFAULT_SQLITE_TIMEOUT}}
    return {
        "pool_size": DEFAULT_PG_POOL_SIZE,
        "max_overflow": DEFAULT_PG_MAX_OVERFLOW,
        "pool_pre_ping": True,
    }


def resolve_database_url(output_dir: Path) -> str:
    """Return DATABASE_URL from env, falling back to SQLite in output_dir."""
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    return f"sqlite:///{output_dir / 'songmaker.db'}"


def init_db(db_url_or_path: Path | str) -> sessionmaker[Session]:
    """Create the database engine, run migrations, and return a session factory.

    Accepts either a database URL string or a Path (legacy SQLite path).
    """
    if isinstance(db_url_or_path, Path):
        db_url_or_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{db_url_or_path}"
    else:
        url = db_url_or_path
        if _is_sqlite(url):
            db_path = Path(url.replace("sqlite:///", ""))
            db_path.parent.mkdir(parents=True, exist_ok=True)

    _run_migrations(url)

    engine = create_engine(url, echo=False, **_build_engine_kwargs(url))

    if _is_sqlite(url):
        _enable_sqlite_pragmas(engine)
        _restrict_permissions(Path(url.replace("sqlite:///", "")))
        log.info("Database initialized: %s (SQLite WAL mode)", url)
    else:
        log.info("Database initialized: %s", url.split("@")[-1] if "@" in url else url)

    return sessionmaker(bind=engine)


def init_test_db(db_path: Path) -> sessionmaker[Session]:
    """Fast test-only database init using create_all() instead of Alembic."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path}"
    engine = create_engine(url, echo=False, connect_args={"timeout": DEFAULT_SQLITE_TIMEOUT})
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
