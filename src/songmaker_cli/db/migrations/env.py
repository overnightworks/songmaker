"""Alembic environment — auto-detects schema changes from SQLAlchemy models."""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from songmaker_cli.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


_ALEMBIC_INI_DEFAULT_URL = "sqlite:///_output/songmaker.db"


def _resolve_db_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url and url != _ALEMBIC_INI_DEFAULT_URL:
        return url
    env_url = os.environ.get("SONGMAKER_DB_URL")
    if env_url:
        return env_url
    db_path = Path.cwd() / "_output" / "songmaker.db"
    return f"sqlite:///{db_path}"


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


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _resolve_db_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
