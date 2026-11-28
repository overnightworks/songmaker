"""The migrations that let a job row name the process that runs it and the lease generation."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType

import pytest
from alembic import command
from support.migration_chain import (
    BARE_JOB_ID,
    assert_column_nullable_empty_and_job_kept,
    column_names,
    insert_bare_job,
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



def test_upgrade_adds_a_nullable_column_and_keeps_an_existing_job_without_an_owner(
    reference_link_database, migration,
):
    engine = _upgraded_with_an_unowned_job(reference_link_database, migration)

    assert_column_nullable_empty_and_job_kept(engine, "jobs", migration.column, BARE_JOB_ID)


def test_downgrade_drops_the_column_and_keeps_the_job(reference_link_database, migration):
    engine = _upgraded_with_an_unowned_job(reference_link_database, migration)
    config, _ = reference_link_database

    command.downgrade(config, migration.module.down_revision)

    assert (migration.column in column_names(engine, "jobs"), job_count(engine)) == (False, 1)
