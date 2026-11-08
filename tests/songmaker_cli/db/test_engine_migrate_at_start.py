"""Every app process migrates at its own start, so starters may race on one database."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from alembic.util.exc import CommandError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from support.postgresql import migration_head

from songmaker_cli.db.engine import init_db

UNKNOWN_REVISION = "ffffffffffff"
# Alembic's `context` is a process-global proxy, so concurrent starters are separate processes,
# like the app's containers.
START_PROCESS = (
    "import os; from songmaker_cli.db.engine import init_db; init_db(os.environ['START_URL'])"
)
START_TIMEOUT_SECONDS = 120


def _stored_revisions(url: URL) -> list[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(text("SELECT version_num FROM alembic_version"))
            return list(rows.scalars())
    finally:
        engine.dispose()


def test_two_concurrent_starts_on_an_empty_database_both_succeed_and_reach_head(
    empty_postgresql_url: URL,
) -> None:
    environment = {
        **os.environ,
        "START_URL": empty_postgresql_url.render_as_string(hide_password=False),
    }
    starts: list[subprocess.Popen[str]] = []
    try:
        for _ in range(2):
            starts.append(
                subprocess.Popen(
                    [sys.executable, "-c", START_PROCESS],
                    env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
            )
        outputs = [start.communicate(timeout=START_TIMEOUT_SECONDS)[0] for start in starts]
    finally:
        for start in starts:
            if start.poll() is None:
                start.kill()
            start.wait()

    assert [start.returncode for start in starts] == [0, 0], outputs
    assert _stored_revisions(empty_postgresql_url) == [migration_head()]


def test_a_start_on_a_database_at_an_unknown_revision_fails_naming_it_and_changes_nothing(
    empty_postgresql_url: URL,
) -> None:
    engine = create_engine(empty_postgresql_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num varchar(32) NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": UNKNOWN_REVISION},
        )
    engine.dispose()

    with pytest.raises(CommandError, match=UNKNOWN_REVISION):
        init_db(empty_postgresql_url)

    assert _stored_revisions(empty_postgresql_url) == [UNKNOWN_REVISION]
