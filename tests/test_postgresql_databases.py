"""The resource contract of tests/support/postgresql.py, the owner of the test databases."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool
from support import postgresql as owner_module
from support.postgresql import (
    ALEMBIC_VERSION_TABLE,
    DatabaseDriftError,
    LeakedConnectionError,
    PostgresqlTestDatabases,
    WorkerDatabaseUnusableError,
    migration_head,
)
from support.postgresql_probe import DATABASE_LINE
from support.repository_root import REPOSITORY_ROOT

from songmaker_cli.db.models import User

PROBE = Path(__file__).resolve().parent / "support" / "postgresql_probe.py"
CHILD_TIMEOUT_SECONDS = 120


@pytest.fixture
def another_run(postgresql_databases):
    """Start owners as further runs would, against the same server; close them afterwards."""
    owners = []

    def start(worker_id: str = "gw0", run_id: str | None = None) -> PostgresqlTestDatabases:
        owner = PostgresqlTestDatabases(
            postgresql_databases.administration_url,
            run_id=run_id or uuid.uuid4().hex,
            worker_id=worker_id,
        )
        owners.append(owner)
        return owner

    yield start
    for owner in owners:
        owner.close()


def _database_exists(administration_url: URL, name: str) -> bool:
    engine = create_engine(administration_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name},
            ).first() is not None
    finally:
        engine.dispose()


def _contents(url: URL) -> dict[str, list[str]]:
    """Every table's rows, order-free, read over a connection of its own."""
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return {
                table: sorted(
                    repr(tuple(row))
                    for row in connection.execute(text(f'SELECT * FROM "{table}"'))
                )
                for table in inspect(connection).get_table_names()
            }
    finally:
        engine.dispose()


def _child_environment() -> dict[str, str]:
    """This environment for a child pytest, without this run's pytest and xdist variables."""
    return {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")}


def _without_the_server(
    environment: dict[str, str], administration_url: URL, replacement: str | None,
) -> dict[str, str]:
    """The environment with the variable that carries the server's URL replaced or removed."""
    configured = administration_url.render_as_string(hide_password=False)
    carriers = [key for key, value in environment.items() if value == configured]
    assert len(carriers) == 1, "exactly one variable carries the server's URL"
    environment = {key: value for key, value in environment.items() if key not in carriers}
    if replacement is not None:
        environment[carriers[0]] = replacement
    return environment


def _child_pytest(*selection: str) -> list[str]:
    return [
        sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:warnings",
        "-n", "0",
        "-s", "-q", *(f"{PROBE}::test_probe_{name}" for name in selection),
    ]


def _announced_databases(output: str) -> list[str]:
    return [
        line.removeprefix(DATABASE_LINE) for line in output.splitlines()
        if line.startswith(DATABASE_LINE)
    ]


def test_runs_and_workers_get_separate_databases_locks_and_cleanup(another_run):
    """Cell 1: concurrent runs and workers."""
    run_id = uuid.uuid4().hex
    first = another_run(worker_id="gw0", run_id=run_id)
    sibling_worker = another_run(worker_id="gw1", run_id=run_id)
    second_run = another_run(worker_id="gw0")
    urls = [owner.worker_url for owner in (first, sibling_worker, second_run)]
    assert len({url.database for url in urls}) == 3

    holder = create_engine(urls[0], poolclass=NullPool)
    contender = create_engine(urls[2], poolclass=NullPool)
    try:
        with holder.connect() as held, contender.connect() as other:
            held.execute(text("SELECT pg_advisory_lock(2300)"))
            assert other.execute(text("SELECT pg_try_advisory_lock(2300)")).scalar_one()
            other.execute(text("SELECT pg_advisory_unlock(2300)"))
            held.execute(text("SELECT pg_advisory_unlock(2300)"))
    finally:
        holder.dispose()
        contender.dispose()

    with pytest.raises(ValueError, match="not a database of this run and worker"):
        second_run.drop_database(urls[0])
    second_run.close()
    assert not _database_exists(first.administration_url, urls[2].database)
    assert _database_exists(first.administration_url, urls[0].database)
    assert _database_exists(first.administration_url, urls[1].database)


def test_a_commit_is_visible_to_a_second_connection_and_a_rollback_is_not(pg_factory):
    """Cell 2: commit visibility."""
    observer = create_engine(pg_factory.kw["bind"].url, poolclass=NullPool)
    try:
        with pg_factory() as session:
            session.add(User(id="committed", username="committed"))
            session.commit()
            session.add(User(id="rolled-back", username="rolled-back"))
            session.flush()
            session.rollback()
        with observer.connect() as connection:
            visible = connection.execute(text("SELECT id FROM users")).scalars().all()
    finally:
        observer.dispose()
    assert visible == ["committed"]


def test_the_reset_removes_writes_and_restores_every_baseline_row(
    postgresql_databases, pg_factory,
):
    """Cell 3: reset and restore."""
    url = postgresql_databases.worker_url
    baseline = _contents(url)
    seeded = [
        table for table, rows in baseline.items() if rows and table != ALEMBIC_VERSION_TABLE
    ]
    assert seeded, "the migrated database holds rows to restore"
    with pg_factory() as session:
        session.add(User(id="written", username="written"))
        session.flush()
        session.execute(text(f"TRUNCATE {', '.join(f'"{table}"' for table in seeded)} CASCADE"))
        session.commit()
    assert _contents(url) != baseline

    postgresql_databases.reset()

    assert _contents(url) == baseline


def test_a_session_left_open_fails_the_reset_and_is_terminated(
    postgresql_databases, pg_factory,
):
    """Cell 4: a leaking session, here on the worker's own database."""
    leaked = pg_factory()
    statement = "SELECT count(*) AS leaked_marker FROM users"
    leaked.execute(text(statement))
    leaked_pid = leaked.execute(text("SELECT pg_backend_pid()")).scalar_one()

    with pytest.raises(LeakedConnectionError) as refusal:
        postgresql_databases.reset()

    report = str(refusal.value)
    assert f"({leaked_pid}, " in report
    assert "leaked_marker" not in report
    with pytest.raises(OperationalError):
        leaked.execute(text("SELECT 1"))
    leaked.close()
    postgresql_databases.reset()


@pytest.mark.parametrize(
    "drift",
    [
        pytest.param("CREATE TABLE stray (id integer)", id="table"),
        pytest.param("ALTER TABLE users ADD COLUMN stray integer", id="column"),
        pytest.param("UPDATE alembic_version SET version_num = 'elsewhere'", id="revision"),
    ],
)
def test_drift_fails_the_reset_and_the_database_is_recreated(another_run, drift):
    """Cell 5: schema or revision drift."""
    owner = another_run()
    drifted = owner.worker_url
    engine = create_engine(drifted, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text(drift))
    engine.dispose()

    with pytest.raises(DatabaseDriftError):
        owner.reset()

    recreated = owner.worker_url
    assert recreated == drifted
    engine = create_engine(recreated, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            schema = inspect(connection)
            assert "stray" not in schema.get_table_names()
            assert "stray" not in {column["name"] for column in schema.get_columns("users")}
            revision = connection.execute(text("SELECT version_num FROM alembic_version"))
            assert revision.scalar_one() == migration_head()
    finally:
        engine.dispose()
    owner.reset()


def test_a_failed_recreation_makes_every_later_use_fail_with_the_drift(
    another_run, monkeypatch,
):
    """Cell 5: when recreation fails, the worker's later database fixtures error."""
    owner = another_run()
    engine = create_engine(owner.worker_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE stray (id integer)"))
    engine.dispose()

    def refuse(_url):
        raise RuntimeError("migration refused")

    monkeypatch.setattr(owner_module, "init_db", refuse)
    with pytest.raises(DatabaseDriftError) as drift:
        owner.reset()

    for later_use in (lambda: owner.worker_url, owner.reset):
        with pytest.raises(WorkerDatabaseUnusableError, match="migration refused") as unusable:
            later_use()
        assert unusable.value.__cause__ is drift.value


def test_an_empty_database_migrates_apart_from_the_worker_database(
    postgresql_databases, empty_postgresql_url, pg_factory,
):
    """Cell 6: migration isolation."""
    worker = postgresql_databases.worker_url
    before = _contents(worker)
    assert empty_postgresql_url.database != worker.database
    assert _contents(empty_postgresql_url) == {}

    engine = create_engine(empty_postgresql_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id integer)"))
        connection.execute(text("CREATE SCHEMA elsewhere"))
    engine.dispose()

    assert _contents(worker) == before
    postgresql_databases.reset()


@pytest.mark.parametrize(
    ("replacement", "refusal"),
    [
        pytest.param(None, "is not set", id="missing"),
        pytest.param("not a database url", "is not a database URL", id="malformed"),
        pytest.param("sqlite:///probe.db", "must name a PostgreSQL server", id="not-postgresql"),
        pytest.param(
            "postgresql://probe:probe@127.0.0.1:9/probe", "OperationalError", id="unreachable",
        ),
    ],
)
def test_without_a_usable_server_database_tests_fail_and_pure_tests_run(
    postgresql_databases, replacement, refusal,
):
    """Cell 7: missing configuration fails database tests; none skips."""
    child = subprocess.run(
        _child_pytest("needs_no_database", "needs_a_database"),
        cwd=REPOSITORY_ROOT,
        env=_without_the_server(
            _child_environment(), postgresql_databases.administration_url, replacement,
        ),
        capture_output=True, text=True, timeout=CHILD_TIMEOUT_SECONDS, check=False,
    )
    assert child.returncode == 1, child.stdout
    assert "1 passed, 1 error" in child.stdout, child.stdout
    assert refusal in child.stdout
    assert "skipped" not in child.stdout


def test_a_failing_and_a_leaking_test_leave_no_database_behind(postgresql_databases):
    """Cells 4 and 8: the leak fails its own test's teardown; the run drops its databases."""
    child = subprocess.run(
        _child_pytest(
            "fails_after_using_its_database", "leaves_a_session_open", "needs_a_database",
        ),
        cwd=REPOSITORY_ROOT,
        env=_child_environment(),
        capture_output=True, text=True, timeout=CHILD_TIMEOUT_SECONDS, check=False,
    )
    output = child.stdout
    assert "1 failed, 2 passed, 1 error" in output, output
    assert "ERROR at teardown of test_probe_leaves_a_session_open" in output
    assert "LeakedConnectionError" in output
    databases = set(_announced_databases(output))
    assert len(databases) == 1
    assert not _database_exists(postgresql_databases.administration_url, databases.pop())


def test_an_interrupted_run_drops_its_databases(postgresql_databases):
    """Cell 8: an interrupt (Ctrl-C) still tears the run's databases down."""
    child = subprocess.Popen(
        _child_pytest("waits_for_an_interrupt"),
        cwd=REPOSITORY_ROOT,
        env=_child_environment(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        announced = next(
            line for line in child.stdout if line.startswith(DATABASE_LINE)
        ).strip().removeprefix(DATABASE_LINE)
        assert _database_exists(postgresql_databases.administration_url, announced)
        child.send_signal(signal.SIGINT)
        output, _ = child.communicate(timeout=CHILD_TIMEOUT_SECONDS)
    finally:
        child.kill()
    assert "KeyboardInterrupt" in output
    assert not _database_exists(postgresql_databases.administration_url, announced)
