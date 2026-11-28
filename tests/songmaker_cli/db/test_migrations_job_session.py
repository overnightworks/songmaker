"""The migrations that let a cover job reference the session that asked and keep its wait."""

from __future__ import annotations

import importlib

from alembic import command
from sqlalchemy import inspect
from support.migration_chain import (
    assert_column_nullable_empty_and_job_kept,
    assert_downgrade_drops_indexed_column_and_keeps_job,
    column_names,
    insert_bare_job,
    job_count,
    seeded_then_upgraded,
)
from support.reference_link_migration import seed_users

MIGRATION = importlib.import_module(
    "songmaker_cli.db.migrations.versions.a7c3e5f19b24_jobs_remember_the_session_that_asked"
)
PREVIOUS_REVISION = "d8b4f2a6c1e9"
COLUMN = "session_id"
WAIT_MIGRATION = importlib.import_module(
    "songmaker_cli.db.migrations.versions.f71349322716_a_busy_cover_job_keeps_the_wait_it_was_given"
)
WAIT_COLUMN = "retry_after_seconds"


def _seed_a_cover_job(engine) -> None:
    seed_users(engine)
    insert_bare_job(engine, job_type="cover")


def _upgraded_with_a_cover_job(database, migration=MIGRATION):
    return seeded_then_upgraded(
        database, migration.down_revision, migration.revision, _seed_a_cover_job,
    )


def _length_of(inspector, table: str, name: str) -> int:
    return next(c for c in inspector.get_columns(table) if c["name"] == name)["type"].length


def test_the_migration_follows_the_previous_revision():
    assert MIGRATION.down_revision == PREVIOUS_REVISION


def test_the_wait_migration_follows_the_session_migration():
    assert WAIT_MIGRATION.down_revision == MIGRATION.revision


def test_upgrade_adds_an_indexed_nullable_key_that_the_database_sets_null(
    reference_link_database,
):
    engine = _upgraded_with_a_cover_job(reference_link_database)
    inspector = inspect(engine)
    column = next(c for c in inspector.get_columns("jobs") if c["name"] == COLUMN)
    assert column["nullable"] is True
    assert column["type"].length == _length_of(inspector, "user_sessions", "id")
    assert any(index["column_names"] == [COLUMN] for index in inspector.get_indexes("jobs"))
    [foreign_key] = [
        fk for fk in inspector.get_foreign_keys("jobs") if fk["constrained_columns"] == [COLUMN]
    ]
    assert foreign_key["referred_table"] == "user_sessions"
    assert foreign_key["options"]["ondelete"].upper() == "SET NULL"


def test_upgrade_keeps_an_existing_job_without_a_session(reference_link_database):
    engine = _upgraded_with_a_cover_job(reference_link_database)
    assert_column_nullable_empty_and_job_kept(engine, COLUMN)


def test_downgrade_drops_the_key_and_keeps_the_job(reference_link_database):
    _upgraded_with_a_cover_job(reference_link_database)
    assert_downgrade_drops_indexed_column_and_keeps_job(
        reference_link_database, COLUMN, PREVIOUS_REVISION, MIGRATION.revision,
    )


def test_the_wait_upgrade_adds_a_nullable_column_and_keeps_the_job_without_a_wait(
    reference_link_database,
):
    engine = _upgraded_with_a_cover_job(reference_link_database, WAIT_MIGRATION)
    assert_column_nullable_empty_and_job_kept(engine, WAIT_COLUMN)


def test_the_wait_downgrade_drops_the_column_keeps_the_job_and_upgrades_again(
    reference_link_database,
):
    config, _ = reference_link_database
    engine = _upgraded_with_a_cover_job(reference_link_database, WAIT_MIGRATION)

    command.downgrade(config, MIGRATION.revision)
    assert WAIT_COLUMN not in column_names(engine, "jobs")
    assert job_count(engine) == 1

    command.upgrade(config, WAIT_MIGRATION.revision)
    assert WAIT_COLUMN in column_names(engine, "jobs")
    assert job_count(engine) == 1
