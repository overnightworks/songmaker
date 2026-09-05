"""Alembic environment — auto-detects schema changes from SQLAlchemy models.

Boundary script: alembic loads and executes this file directly. It reads
DATABASE_URL from os.environ rather than going through Settings so the
migrate container does not need to plumb unrelated Settings env vars
(REDIS_URL, SESSION_SECRET, SONGMAKER_INTERNAL_TOKEN) just to run
``alembic upgrade``.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from songmaker_cli.db.migration_logging import configure_migration_logging
from songmaker_cli.db.models import Base

config = context.config

if config.config_file_name is not None:
    configure_migration_logging()

target_metadata = Base.metadata


def _resolve_db_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    env_url = os.environ.get("DATABASE_URL")
    if not env_url:
        raise RuntimeError(
            "DATABASE_URL is required for alembic migrations — "
            "set it in the environment before running `alembic upgrade`.",
        )
    return env_url


def run_migrations_offline() -> None:
    url = _resolve_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


MIGRATION_LOCK_ID = 7_301_489_201


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _resolve_db_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        is_postgres = connection.dialect.name == "postgresql"
        if is_postgres:
            connection.execute(text(f"SELECT pg_advisory_lock({MIGRATION_LOCK_ID})"))
            connection.commit()
        try:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            if is_postgres:
                connection.execute(text(f"SELECT pg_advisory_unlock({MIGRATION_LOCK_ID})"))
                connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
