"""The migration that lets a job row reference the session that asked for it."""

from __future__ import annotations

import importlib

import sqlalchemy as sa
from alembic import command
from sqlalchemy import inspect
from support.migration_chain import (
    column_names,
    insert_bare_job,
    is_on_the_single_chain,
    seeded_then_upgraded,
)
from support.reference_link_migration import seed_users

MIGRATION = importlib.import_module(
    "songmaker_cli.db.migrations.versions.a7c3e5f19b24_jobs_remember_the_session_that_asked"
)
PREVIOUS_REVISION = "d8b4f2a6c1e9"
COLUMN = "session_id"
JOBS_SESSION = sa.table("jobs", sa.column(COLUMN))


def _seed_a_cover_job(engine) -> None:
    seed_users(engine)
    insert_bare_job(engine, job_type="cover")


def _upgraded_with_a_cover_job(database):
    return seeded_then_upgraded(database, PREVIOUS_REVISION, MIGRATION.revision, _seed_a_cover_job)


def _length_of(inspector, table: str, name: str) -> int:
    return next(c for c in inspector.get_columns(table) if c["name"] == name)["type"].length


def _job_sessions(engine) -> list[str | None]:
    with engine.connect() as connection:
        return list(connection.execute(sa.select(JOBS_SESSION.c[COLUMN])).scalars())


def test_the_migration_follows_the_previous_revision_on_the_single_chain():
    assert MIGRATION.down_revision == PREVIOUS_REVISION
    assert is_on_the_single_chain(MIGRATION.revision)


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
    assert _job_sessions(engine) == [None]


def test_downgrade_drops_the_key_and_keeps_the_job(reference_link_database):
    config, _ = reference_link_database
    engine = _upgraded_with_a_cover_job(reference_link_database)
    command.downgrade(config, PREVIOUS_REVISION)
    assert COLUMN not in column_names(engine, "jobs")
    assert not any(
        index["column_names"] == [COLUMN] for index in inspect(engine).get_indexes("jobs")
    )
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT count(*) FROM jobs")).scalar_one() == 1
    command.upgrade(config, MIGRATION.revision)
    assert COLUMN in column_names(engine, "jobs")
