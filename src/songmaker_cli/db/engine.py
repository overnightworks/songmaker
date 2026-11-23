"""Database engine and session management."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.constants import (
    STORE_STARTUP_CONNECT_TIMEOUT_SECONDS,
    STORE_STARTUP_RETRY_DELAY_SECONDS,
    STORE_STARTUP_WAIT_SECONDS,
)
from songmaker_cli.db.database_url import connection_url_from_settings
from songmaker_cli.db.soft_delete import install_soft_delete_filter
from songmaker_cli.settings import get_settings

install_soft_delete_filter()

log = logging.getLogger(__name__)

MIGRATIONS_DIR = str(Path(__file__).parent / "migrations")

DATABASE_NOT_AT_HEAD_MESSAGE = (
    "The database is at revision {stored}, not at head {head}. The migrate init container "
    "owns migrations and this process never migrates; Kubernetes restarts this "
    "process until the head matches."
)

_RETRIED_SERVER_FATALS = (
    "the database system is starting up",
    "the database system is shutting down",
    "the database system is in recovery mode",
)


class DatabaseNotAtHeadError(RuntimeError):
    """The database revision differs from the script head, or the database is unversioned."""


def resolve_database_url() -> URL:
    """Return the full connection URL from Settings (base plus password file).

    A ``URL`` object, so the password never travels as plain text.
    """
    return connection_url_from_settings(get_settings())


def _is_connection_level_failure(error: OperationalError) -> bool:
    # A message without a server-sent FATAL is a client or network error (refused,
    # unresolved, timed out, reset) that a wait can outlast; psycopg 3 sets no
    # sqlstate on a connect-time failure either. Other server FATALs (password,
    # database, pg_hba) are configuration a wait cannot fix.
    message = str(error.orig).lower()
    if "fatal:" not in message:
        return True
    return any(fragment in message for fragment in _RETRIED_SERVER_FATALS)


def _probe_database(url: URL | str) -> None:
    engine = create_engine(
        url, connect_args={"connect_timeout": STORE_STARTUP_CONNECT_TIMEOUT_SECONDS}
    )
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
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


def _script_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    cfg.set_main_option("script_location", MIGRATIONS_DIR)
    head = ScriptDirectory.from_config(cfg).get_current_head()
    if head is None:
        raise RuntimeError("The migration chain has no head")
    return head


def _stored_revision(url: URL | str) -> str | None:
    from alembic.runtime.migration import MigrationContext

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def require_database_at_head(url: URL | str) -> None:
    """Raise ``DatabaseNotAtHeadError`` unless the database holds the script head revision.

    Never migrates and never stamps: an unversioned database counts as behind.
    """
    head = _script_head()
    stored = _stored_revision(url)
    if stored != head:
        raise DatabaseNotAtHeadError(
            DATABASE_NOT_AT_HEAD_MESSAGE.format(stored=stored or "none", head=head)
        )


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
    """Wait for the database, require it at head, and return a session factory."""
    wait_for_database(url)
    require_database_at_head(url)
    return connect_db(url)
