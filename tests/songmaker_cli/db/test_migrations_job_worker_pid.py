"""The migration that drops the process id of a job's worker, nothing reads it."""

from __future__ import annotations

import importlib

import sqlalchemy as sa
from alembic import command
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from support.migration_chain import (
    column_names,
    insert_bare_job,
    job_count,
    seeded_then_upgraded,
)

MIGRATION = importlib.import_module(
    "songmaker_cli.db.migrations.versions.a8c4f2d6e913_jobs_lose_the_worker_process_id"
)
COLUMN = "worker_pid"
STALE_PROCESS_ID = 4242


def _insert_job_run_by_a_worker(engine: Engine) -> None:
    insert_bare_job(engine)
    jobs = sa.table("jobs", sa.column("id"), sa.column(COLUMN))
    with engine.begin() as connection:
        connection.execute(
            sa.update(jobs).where(jobs.c.id == "job").values({COLUMN: STALE_PROCESS_ID}),
        )


def _job_rows_without_the_column(engine: Engine) -> list[dict[str, object]]:
    with engine.connect() as connection:
        rows = connection.execute(sa.text("SELECT * FROM jobs ORDER BY id")).mappings().all()
    return [{key: value for key, value in row.items() if key != COLUMN} for row in rows]


def _job_run_by_a_worker_before_the_upgrade(database) -> tuple[Engine, list[dict[str, object]]]:
    config, engine = database
    command.upgrade(config, MIGRATION.down_revision)
    _insert_job_run_by_a_worker(engine)
    rows = _job_rows_without_the_column(engine)
    command.upgrade(config, MIGRATION.revision)
    return engine, rows


def test_upgrade_drops_the_column_and_keeps_every_job_with_its_other_values(
    reference_link_database,
):
    engine, rows_before = _job_run_by_a_worker_before_the_upgrade(reference_link_database)

    assert (COLUMN in column_names(engine, "jobs"), _job_rows_without_the_column(engine)) == (
        False, rows_before,
    )


def test_downgrade_adds_the_column_back_nullable_and_empty_and_keeps_the_job(
    reference_link_database,
):
    config, _ = reference_link_database
    engine = seeded_then_upgraded(
        reference_link_database, MIGRATION.down_revision, MIGRATION.revision, insert_bare_job,
    )

    command.downgrade(config, MIGRATION.down_revision)

    jobs = sa.table("jobs", sa.column(COLUMN))
    column = next(c for c in inspect(engine).get_columns("jobs") if c["name"] == COLUMN)
    with engine.connect() as connection:
        values = list(connection.execute(sa.select(jobs.c[COLUMN])).scalars())
    assert (column["nullable"], values, job_count(engine)) == (True, [None], 1)
