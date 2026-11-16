"""The migrations that let a job row name the process that runs it and the lease generation."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType

import pytest
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


@dataclass(frozen=True)
class OwnerColumnMigration:
    module: ModuleType
    column: str


MIGRATIONS = [
    OwnerColumnMigration(
        importlib.import_module(
            "songmaker_cli.db.migrations.versions.d2f6b8a4c7e1_jobs_name_their_owner"
        ),
        "owner_id",
    ),
    OwnerColumnMigration(
        importlib.import_module(
            "songmaker_cli.db.migrations.versions"
            ".e5a2c8f1d703_jobs_name_the_lease_generation_of_their_owner"
        ),
        "owner_generation",
    ),
]


@pytest.fixture(params=MIGRATIONS, ids=lambda migration: migration.column)
def migration(request) -> OwnerColumnMigration:
    return request.param


def _upgraded_with_an_unowned_job(database, migration: OwnerColumnMigration):
    return seeded_then_upgraded(
        database, migration.module.down_revision, migration.module.revision, insert_bare_job,
    )


def test_the_migration_is_on_the_single_chain(migration):
    assert is_on_the_single_chain(migration.module.revision)


def test_upgrade_adds_a_nullable_column_and_keeps_an_existing_job_without_an_owner(
    reference_link_database, migration,
):
    engine = _upgraded_with_an_unowned_job(reference_link_database, migration)

    jobs = sa.table("jobs", sa.column(migration.column))
    column = next(c for c in inspect(engine).get_columns("jobs") if c["name"] == migration.column)
    with engine.connect() as connection:
        values = list(connection.execute(sa.select(jobs.c[migration.column])).scalars())
    assert (column["nullable"], values, job_count(engine)) == (True, [None], 1)


def test_downgrade_drops_the_column_and_keeps_the_job(reference_link_database, migration):
    engine = _upgraded_with_an_unowned_job(reference_link_database, migration)
    config, _ = reference_link_database

    command.downgrade(config, migration.module.down_revision)

    assert (migration.column in column_names(engine, "jobs"), job_count(engine)) == (False, 1)
