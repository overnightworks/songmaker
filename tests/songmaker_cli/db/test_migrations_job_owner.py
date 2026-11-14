"""The migration that lets a job row name the process that runs it."""

from __future__ import annotations

import importlib

import sqlalchemy as sa
from alembic import command
from sqlalchemy import inspect
from support.migration_chain import (
    column_names,
    insert_bare_job,
    is_on_the_single_chain,
    job_count,
    seeded_then_upgraded,
)

MIGRATION = importlib.import_module(
    "songmaker_cli.db.migrations.versions.d2f6b8a4c7e1_jobs_name_their_owner"
)
COLUMN = "owner_id"
JOBS_OWNER = sa.table("jobs", sa.column(COLUMN))


def _upgraded_with_an_unowned_job(database):
    return seeded_then_upgraded(
        database, MIGRATION.down_revision, MIGRATION.revision, insert_bare_job,
    )


def test_the_migration_is_on_the_single_chain():
    assert is_on_the_single_chain(MIGRATION.revision)


def test_upgrade_adds_a_nullable_column_and_keeps_an_existing_job_without_an_owner(
    reference_link_database,
):
    engine = _upgraded_with_an_unowned_job(reference_link_database)

    column = next(c for c in inspect(engine).get_columns("jobs") if c["name"] == COLUMN)
    with engine.connect() as connection:
        owners = list(connection.execute(sa.select(JOBS_OWNER.c[COLUMN])).scalars())
    assert (column["nullable"], owners, job_count(engine)) == (True, [None], 1)


def test_downgrade_drops_the_column_and_keeps_the_job(reference_link_database):
    engine = _upgraded_with_an_unowned_job(reference_link_database)
    config, _ = reference_link_database

    command.downgrade(config, MIGRATION.down_revision)

    assert (COLUMN in column_names(engine, "jobs"), job_count(engine)) == (False, 1)
