"""Questions about the alembic revision chain that no test answers by pinning the head."""

from __future__ import annotations

from collections.abc import Callable

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from support.repository_root import REPOSITORY_ROOT


def is_on_the_single_chain(revision: str) -> bool:
    """Whether the script directory has exactly one head and `revision` is among its ancestors."""
    scripts = ScriptDirectory.from_config(Config(str(REPOSITORY_ROOT / "alembic.ini")))
    heads = scripts.get_heads()
    if len(heads) != 1:
        return False
    return revision in {script.revision for script in scripts.iterate_revisions(heads[0], "base")}


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


def insert_bare_job(engine: Engine, *, job_type: str = "generate") -> None:
    """Insert the job ``job`` with only the columns every revision's ``jobs`` table has.

    The SQLite chain builds a narrower table than PostgreSQL's, so the timestamps join only
    where they exist.
    """
    present = column_names(engine, "jobs")
    timestamps = [name for name in ("heartbeat_at", "started_at") if name in present]
    names = ("id", "type", "status", "progress", *timestamps)
    jobs = sa.table("jobs", *(sa.column(name) for name in names))
    with engine.begin() as connection:
        connection.execute(sa.insert(jobs).values(
            id="job", type=job_type, status="queued", progress=0.0,
            **{name: sa.func.current_timestamp() for name in timestamps},
        ))
