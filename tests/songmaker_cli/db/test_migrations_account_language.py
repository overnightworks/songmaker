"""The migration that lets the session row keep the account's language tag."""

from __future__ import annotations

import importlib

from alembic import command
from sqlalchemy import inspect, text
from support.migration_chain import column_names, seeded_then_upgraded
from support.reference_link_migration import execute, seed_users

MIGRATION = importlib.import_module(
    "songmaker_cli.db.migrations.versions.c4e8a2d6f913_session_row_keeps_the_account_language",
)


def _seed_session(engine) -> None:
    seed_users(engine)
    execute(
        engine,
        "INSERT INTO user_sessions (id, user_id, created_at, expires_at) "
        "VALUES ('s1', 'u1', '2026-10-01 00:00:00', '2026-10-08 00:00:00')",
    )


def _sessions(engine) -> list[tuple]:
    with engine.connect() as connection:
        return list(connection.execute(text("SELECT id FROM user_sessions")))


def test_upgrade_adds_a_nullable_column_and_a_session_from_before_reads_none(
    reference_link_database,
) -> None:
    engine = seeded_then_upgraded(
        reference_link_database, MIGRATION.down_revision, MIGRATION.revision, _seed_session,
    )

    columns = inspect(engine).get_columns("user_sessions")
    assert next(c for c in columns if c["name"] == "account_language")["nullable"] is True
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT account_language FROM user_sessions"))
        assert stored.scalar() is None
    assert _sessions(engine) == [("s1",)]


def test_downgrade_drops_the_column_and_keeps_the_sessions(reference_link_database) -> None:
    config, _ = reference_link_database
    engine = seeded_then_upgraded(
        reference_link_database, MIGRATION.down_revision, MIGRATION.revision, _seed_session,
    )

    command.downgrade(config, MIGRATION.down_revision)

    assert "account_language" not in column_names(engine, "user_sessions")
    assert _sessions(engine) == [("s1",)]
