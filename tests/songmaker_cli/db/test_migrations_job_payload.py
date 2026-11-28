"""The migration that lets a job row carry its arguments and the time it waits for."""

from __future__ import annotations

import importlib

import pytest
from alembic import command
from sqlalchemy import inspect
from support.migration_chain import (
    BARE_JOB_ID,
    assert_column_nullable_empty_and_job_kept,
    column_names,
    insert_bare_job,
    job_count,
    seeded_then_upgraded,
)

MIGRATION = importlib.import_module(
    "songmaker_cli.db.migrations.versions.a3c9e1f7b254_jobs_carry_their_arguments_and_run_after"
)
COLUMNS = ("payload", "run_after")


def _upgraded_with_a_job_of_the_old_shape(database):
    return seeded_then_upgraded(
        database, MIGRATION.down_revision, MIGRATION.revision, insert_bare_job,
    )



@pytest.mark.parametrize("column", COLUMNS)
def test_upgrade_adds_a_nullable_column_and_keeps_an_existing_job_without_a_value(
    reference_link_database, column,
):
    engine = _upgraded_with_a_job_of_the_old_shape(reference_link_database)

    assert_column_nullable_empty_and_job_kept(engine, "jobs", column, BARE_JOB_ID)


def test_upgrade_stores_the_payload_as_binary_json_and_the_wait_with_its_zone(
    reference_link_database,
):
    engine = _upgraded_with_a_job_of_the_old_shape(reference_link_database)

    types = {c["name"]: c["type"] for c in inspect(engine).get_columns("jobs")}
    assert (type(types["payload"]).__name__, types["run_after"].timezone) == ("JSONB", True)


def test_downgrade_drops_both_columns_and_keeps_the_job(reference_link_database):
    engine = _upgraded_with_a_job_of_the_old_shape(reference_link_database)
    config, _ = reference_link_database

    command.downgrade(config, MIGRATION.down_revision)

    assert (set(COLUMNS) & column_names(engine, "jobs"), job_count(engine)) == (set(), 1)
