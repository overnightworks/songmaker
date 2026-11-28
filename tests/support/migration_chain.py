"""Questions about the alembic revision chain that no test answers by pinning the head."""

from __future__ import annotations

from collections.abc import Callable

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

BARE_JOB_ID = "job"


def seeded_then_upgraded(
    database: tuple[Config, Engine],
    previous_revision: str,
    revision: str,
    seed: Callable[[Engine], None],
) -> Engine:
    """Seed the world at `previous_revision`, then upgrade to `revision`; return the engine."""
    config, engine = database
    command.upgrade(config, previous_revision)
    seed(engine)
    command.upgrade(config, revision)
    return engine


def column_names(engine: Engine, table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table)}


def frozen_table(name: str, column_names_of_row: tuple[str, ...], column: str) -> sa.TableClause:
    """A table as a migration test writes it: the named columns plus the one under test."""
    return sa.table(name, *(sa.column(each) for each in (*column_names_of_row, column)))


def stored_values(engine: Engine, table: str, column: str) -> dict[str, object]:
    """The value of `column` of every row of `table`, by the row's id."""
    rows = sa.table(table, sa.column("id"), sa.column(column))
    with engine.connect() as connection:
        return dict(connection.execute(sa.select(rows.c.id, rows.c[column])).all())


def assert_column_nullable_empty_and_job_kept(engine: Engine, column: str) -> None:
    """`column` of ``jobs`` is nullable and empty, and the job `BARE_JOB_ID` is its only row."""
    [stored] = [c for c in inspect(engine).get_columns("jobs") if c["name"] == column]
    assert (stored["nullable"], stored_values(engine, "jobs", column)) == (
        True, {BARE_JOB_ID: None},
    )


def assert_downgrade_drops_indexed_column_and_keeps_job(
    database: tuple[Config, Engine], column: str, previous_revision: str, revision: str,
) -> None:
    """Downgrading to `previous_revision` drops `column` of ``jobs`` and its index, keeps the job.

    The upgrade to `revision` then restores the column.
    """
    config, engine = database
    command.downgrade(config, previous_revision)
    assert column not in column_names(engine, "jobs")
    assert not any(
        index["column_names"] == [column] for index in inspect(engine).get_indexes("jobs")
    )
    assert job_count(engine) == 1
    command.upgrade(config, revision)
    assert column in column_names(engine, "jobs")


def job_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return connection.execute(sa.text("SELECT count(*) FROM jobs")).scalar_one()


def insert_bare_job(
    engine: Engine, *, job_type: str = "generate", status: str = "queued",
) -> None:
    """Insert the job `BARE_JOB_ID` with only the columns every revision's ``jobs`` table has.

    Older revisions' ``jobs`` tables lack the timestamp columns, so they join only where
    they exist.
    """
    present = column_names(engine, "jobs")
    timestamps = [name for name in ("heartbeat_at", "started_at") if name in present]
    names = ("id", "type", "status", "progress", *timestamps)
    jobs = sa.table("jobs", *(sa.column(name) for name in names))
    with engine.begin() as connection:
        connection.execute(sa.insert(jobs).values(
            id=BARE_JOB_ID, type=job_type, status=status, progress=0.0,
            **{name: sa.func.current_timestamp() for name in timestamps},
        ))
