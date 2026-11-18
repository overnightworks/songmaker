"""A process starts only on a database at head; concurrent `alembic upgrade head` runs serialise."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from support.postgresql import migration_head, upgrade_to_head
from support.repository_root import REPOSITORY_ROOT

from songmaker_cli.db.engine import DatabaseNotAtHeadError, init_db
from songmaker_cli.db.models import Base

BEHIND_REVISION = "ffffffffffff"
# Alembic's `context` is a process-global proxy, so concurrent upgrades are separate processes,
# like the init containers of two surge pods.
UPGRADE_COMMAND = [sys.executable, "-m", "alembic", "upgrade", "head"]
UPGRADE_TIMEOUT_SECONDS = 120


def _stored_revisions(url: URL) -> list[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(text("SELECT version_num FROM alembic_version"))
            return list(rows.scalars())
    finally:
        engine.dispose()


def _execute(url: URL, statement: str, **parameters: str) -> None:
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text(statement), parameters)
    engine.dispose()


def test_two_concurrent_upgrades_on_an_empty_database_both_succeed_and_migrate_once(
    empty_postgresql_url: URL,
) -> None:
    environment = {
        **os.environ,
        "DATABASE_URL": empty_postgresql_url.render_as_string(hide_password=False),
    }
    upgrades: list[subprocess.Popen[str]] = []
    try:
        for _ in range(2):
            upgrades.append(
                subprocess.Popen(
                    UPGRADE_COMMAND,
                    cwd=REPOSITORY_ROOT,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            )
        outputs = [upgrade.communicate(timeout=UPGRADE_TIMEOUT_SECONDS)[0] for upgrade in upgrades]
    finally:
        for upgrade in upgrades:
            if upgrade.poll() is None:
                upgrade.kill()
            upgrade.wait()

    assert [upgrade.returncode for upgrade in upgrades] == [0, 0], outputs
    assert _stored_revisions(empty_postgresql_url) == [migration_head()]


def test_a_start_on_a_database_at_head_returns_a_session_factory(
    empty_postgresql_url: URL,
) -> None:
    upgrade_to_head(empty_postgresql_url)

    init_db(empty_postgresql_url).kw["bind"].dispose()


def test_a_start_on_a_database_behind_head_fails_naming_both_revisions_and_changes_nothing(
    empty_postgresql_url: URL,
) -> None:
    upgrade_to_head(empty_postgresql_url)
    _execute(
        empty_postgresql_url,
        "UPDATE alembic_version SET version_num = :revision",
        revision=BEHIND_REVISION,
    )

    with pytest.raises(DatabaseNotAtHeadError) as refusal:
        init_db(empty_postgresql_url)

    assert BEHIND_REVISION in str(refusal.value)
    assert migration_head() in str(refusal.value)
    assert _stored_revisions(empty_postgresql_url) == [BEHIND_REVISION]


def test_a_start_on_an_unversioned_database_with_tables_fails_and_stamps_nothing(
    empty_postgresql_url: URL,
) -> None:
    engine = create_engine(empty_postgresql_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    with pytest.raises(DatabaseNotAtHeadError, match=migration_head()):
        init_db(empty_postgresql_url)

    engine = create_engine(empty_postgresql_url)
    try:
        with engine.connect() as connection:
            versioned = connection.execute(
                text("SELECT to_regclass('alembic_version')")
            ).scalar_one()
    finally:
        engine.dispose()
    assert versioned is None


def test_a_start_on_an_empty_database_fails(empty_postgresql_url: URL) -> None:
    with pytest.raises(DatabaseNotAtHeadError, match=migration_head()):
        init_db(empty_postgresql_url)
