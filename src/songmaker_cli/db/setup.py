"""One-time database setup — create PostgreSQL user, database, and run migrations."""

from __future__ import annotations

import logging
from urllib.parse import urlparse, urlunparse

from songmaker_cli.db.engine import init_db

log = logging.getLogger(__name__)


def _parse_credentials(url: str) -> tuple[str, str, str, str]:
    parsed = urlparse(url)
    username = parsed.username or "songmaker"
    password = parsed.password or ""
    db_name = parsed.path.lstrip("/")
    maintenance_url = urlunparse(parsed._replace(
        netloc=f"{parsed.hostname}:{parsed.port or 5432}",
        path="/postgres",
    ))
    return username, password, db_name, maintenance_url


def _bootstrap_pg(url: str) -> None:
    from sqlalchemy import create_engine, text

    username, password, db_name, maintenance_url = _parse_credentials(url)
    engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")

    with engine.connect() as conn:
        user_exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :name"),
            {"name": username},
        ).scalar()
        if user_exists:
            log.info("PostgreSQL role '%s' already exists", username)
        else:
            conn.execute(text(
                f"CREATE ROLE \"{username}\" WITH LOGIN PASSWORD '{password}'"
            ))
            log.info("Created PostgreSQL role '%s'", username)

        db_exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": db_name},
        ).scalar()
        if db_exists:
            log.info("Database '%s' already exists", db_name)
        else:
            conn.execute(text(f'CREATE DATABASE "{db_name}" OWNER "{username}"'))
            log.info("Created database '%s' owned by '%s'", db_name, username)

    engine.dispose()


def create_database(url: str) -> None:
    _bootstrap_pg(url)
    init_db(url)
    log.info("Migrations applied")
