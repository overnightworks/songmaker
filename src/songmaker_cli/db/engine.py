"""Database engine and session management."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.constants import (
    STORE_STARTUP_CONNECT_TIMEOUT_SECONDS,
    STORE_STARTUP_RETRY_DELAY_SECONDS,
    STORE_STARTUP_WAIT_SECONDS,
)
from songmaker_cli.db.database_url import connection_url_from_settings
from songmaker_cli.db.models import Base
from songmaker_cli.db.soft_delete import install_soft_delete_filter
from songmaker_cli.settings import get_settings

install_soft_delete_filter()

log = logging.getLogger(__name__)

MIGRATIONS_DIR = str(Path(__file__).parent / "migrations")

_DEFAULT_SQLITE_TIMEOUT = 30

_RETRIED_SERVER_FATALS = (
    "the database system is starting up",
    "the database system is shutting down",
    "the database system is in recovery mode",
)


def resolve_database_url() -> URL:
    """Return the full connection URL from Settings (base plus password file).

    A ``URL`` object, so the password never travels as plain text.
    """
    return connection_url_from_settings(get_settings())


def _is_connection_level_failure(error: OperationalError) -> bool:
    # A message without a server-sent FATAL is a client or network error (refused,
    # unresolved, timed out, reset) that a wait can outlast; psycopg2 sets no pgcode
    # before authentication. Other server FATALs (password, database, pg_hba) are
    # configuration a wait cannot fix.
    message = str(error.orig).lower()
    if "fatal:" not in message:
        return True
    return any(fragment in message for fragment in _RETRIED_SERVER_FATALS)


def _probe_database(url: URL | str) -> None:
    engine = create_engine(
        url, connect_args={"connect_timeout": STORE_STARTUP_CONNECT_TIMEOUT_SECONDS},
    )
    try:
        with engine.connect():
            pass
    finally:
        engine.dispose()


def wait_for_database(
    url: URL | str,
    *,
    probe: Callable[[URL | str], None] = _probe_database,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Block until the database accepts a connection; raise the last error after the bound."""
    shown = make_url(url)
    log.info(
        "Waiting up to %ss for the database at %s:%s",
        STORE_STARTUP_WAIT_SECONDS, shown.host, shown.port,
    )
    deadline = now() + STORE_STARTUP_WAIT_SECONDS
    while True:
        try:
            probe(url)
        except OperationalError as error:
            if not _is_connection_level_failure(error) or now() >= deadline:
                raise
            sleep(STORE_STARTUP_RETRY_DELAY_SECONDS)
        else:
            log.info("Database answers at %s:%s", shown.host, shown.port)
            return


def _run_migrations(url: URL | str) -> None:
    """Run Alembic migrations, stamping existing databases that lack alembic_version."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", MIGRATIONS_DIR)
    # configparser interpolates "%", so the rendered URL doubles it.
    rendered_url = make_url(url).render_as_string(hide_password=False)
    cfg.set_main_option("sqlalchemy.url", rendered_url.replace("%", "%%"))

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


def connect_db(url: URL | str) -> sessionmaker[Session]:
    """Create the PostgreSQL engine and a session factory — no migrations.

    Pure connection setup: no DDL, no schema check. Use this from anything
    that must never touch the schema as a side effect of connecting — a
    one-time data script is the reason this exists, since running it after
    a failed deploy migration must not silently drag the schema to head
    before the script has even reported what it would do.
    """
    settings = get_settings()
    engine = create_engine(
        url, echo=False,
        hide_parameters=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
    )

    shown = make_url(url)
    log.info("Database initialized: %s:%s/%s", shown.host, shown.port, shown.database)
    return sessionmaker(bind=engine)


def init_db(url: URL | str) -> sessionmaker[Session]:
    """Wait for the database, run migrations, and return a session factory."""
    wait_for_database(url)
    _run_migrations(url)
    return connect_db(url)


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
    _seed_available_models(engine)
    return sessionmaker(bind=engine)


def _seed_available_models(engine) -> None:
    from sqlalchemy import text

    from songmaker_cli.constants import MODEL_AVAILABLE_MODES, MODEL_DEFAULT_MODE

    stmt = text(
        "INSERT OR IGNORE INTO available_models (id, is_active) VALUES (:id, :active)",
    )
    with engine.begin() as conn:
        for mode in MODEL_AVAILABLE_MODES:
            conn.execute(stmt, {"id": mode, "active": int(mode == MODEL_DEFAULT_MODE)})
