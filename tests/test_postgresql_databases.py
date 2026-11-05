"""The resource contract of tests/support/postgresql.py, the owner of the test databases."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from support import postgresql as owner_module
from support.postgres_lock_harness import WAIT_SECONDS, in_thread, wait_until_blocked_behind
from support.postgresql import (
    ALEMBIC_VERSION_TABLE,
    CONNECT_TIMEOUT_SECONDS,
    DROP_TIMEOUT_MILLISECONDS,
    DatabaseDriftError,
    LeakedConnectionError,
    PostgresqlTestDatabases,
    WorkerDatabaseUnusableError,
    database_name,
    migration_head,
)
from support.postgresql_probe import DATABASE_LINE
from support.repository_root import REPOSITORY_ROOT

from songmaker_cli.db.models import User

PROBE = Path(__file__).resolve().parent / "support" / "postgresql_probe.py"
CHILD_TIMEOUT_SECONDS = 120
THREAD_POLL_SECONDS = 0.02
_END_BACKENDS_OF = text(
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :database"
)
_WAITS_ON_A_LOCK = text("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid")


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


def _stop_thread_working_in(
    thread: threading.Thread, administration_url: URL, database: str,
) -> bool:
    """Join the thread; while it lives, end every backend of the database and join again.

    Ending those backends ends every statement the owner runs in that database. The longest
    it runs elsewhere is the drop of a database it recreates, so the wait covers that drop.
    """
    if thread.ident is None:
        return True
    thread.join(WAIT_SECONDS)
    deadline = time.monotonic() + DROP_TIMEOUT_MILLISECONDS / 1000 + CONNECT_TIMEOUT_SECONDS
    engine = create_engine(administration_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        while thread.is_alive() and time.monotonic() < deadline:
            with engine.connect() as administration:
                administration.execute(_END_BACKENDS_OF, {"database": database})
            thread.join(THREAD_POLL_SECONDS)
    finally:
        engine.dispose()
    return not thread.is_alive()


def _wait_until_waiting_on_a_lock_or_done(
    administration_url: URL, pid: int, thread: threading.Thread,
) -> None:
    """Return once the backend waits on a lock or the thread driving it has ended."""
    deadline = time.monotonic() + WAIT_SECONDS
    engine = create_engine(administration_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with engine.connect() as observer:
            while thread.is_alive():
                if observer.execute(_WAITS_ON_A_LOCK, {"pid": pid}).scalar():
                    return
                if time.monotonic() >= deadline:
                    pytest.fail(f"{thread.name} neither waited on a lock nor ended")
                time.sleep(THREAD_POLL_SECONDS)
    finally:
        engine.dispose()


def _child_environment() -> dict[str, str]:
    """This environment for a child pytest, without this run's pytest and xdist variables."""
    return {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")}


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


@pytest.mark.parametrize("option", ["dbname", "database"])
def test_a_url_option_that_selects_a_database_is_refused_before_anything_is_created(
    postgresql_databases, option,
):
    """Cell 1: the administration URL cannot redirect the owner's databases elsewhere."""
    administration_url = postgresql_databases.administration_url
    redirecting = administration_url.update_query_dict({option: administration_url.database})
    run_id = uuid.uuid4().hex

    with pytest.raises(ValueError, match=option):
        PostgresqlTestDatabases(redirecting, run_id=run_id, worker_id="gw0")

    assert not _database_exists(administration_url, database_name(run_id, "gw0"))


def test_every_owned_connection_reaches_the_owned_database(another_run):
    """Cell 1: migrations, resets and tests connect to the database the owner named."""
    owner = another_run()
    for url in (owner.worker_url, owner.create_empty_database()):
        engine = create_engine(url, poolclass=NullPool)
        try:
            with engine.connect() as connection:
                reached = connection.execute(text("SELECT current_database()")).scalar_one()
        finally:
            engine.dispose()
        assert reached == url.database


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
    pg_factory.kw["bind"].dispose()

    postgresql_databases.reset()

    assert _contents(url) == baseline


@pytest.mark.parametrize(
    ("isolation_level", "leaked_statement"),
    [
        pytest.param(None, "SELECT count(*) AS leaked_marker FROM users", id="table-lock"),
        pytest.param(None, "SELECT 1 AS leaked_marker", id="open-transaction"),
        pytest.param(
            "AUTOCOMMIT", "SELECT pg_advisory_lock(2300) AS leaked_marker", id="advisory-lock",
        ),
    ],
)
def test_a_connection_left_open_fails_the_reset_and_only_it_is_terminated(
    postgresql_databases, pg_factory, another_run, isolation_level, leaked_statement,
):
    """Cell 4: a leaking connection on the worker's own database; others stay untouched."""
    bystanders = [
        create_engine(url, poolclass=NullPool)
        for url in (another_run().worker_url, postgresql_databases.administration_url)
    ]
    held = [engine.connect() for engine in bystanders]
    leaking = pg_factory.kw["bind"]
    if isolation_level is not None:
        leaking = leaking.execution_options(isolation_level=isolation_level)
    leaked = leaking.connect()
    leaked.execute(text(leaked_statement))
    leaked_pid = leaked.execute(text("SELECT pg_backend_pid()")).scalar_one()
    alive = text("SELECT 1")
    try:
        for bystander in held:
            bystander.execute(alive)

        with pytest.raises(LeakedConnectionError) as refusal:
            postgresql_databases.reset()

        report = str(refusal.value)
        assert re.search(rf"\b{leaked_pid}\b", report)
        assert "leaked_marker" not in report
        with pytest.raises(OperationalError):
            leaked.execute(alive)
        assert [bystander.execute(alive).scalar_one() for bystander in held] == [1, 1]
    finally:
        leaked.invalidate()
        for bystander in held:
            bystander.close()
        for engine in bystanders:
            engine.dispose()
    postgresql_databases.reset()


def test_a_write_from_a_connection_left_open_never_outlives_the_reset(
    postgresql_databases, pg_factory, monkeypatch,
):
    """Cell 4: a leaked connection holding no lock writes once the reset looks for clients."""
    url = postgresql_databases.worker_url
    baseline = _contents(url)
    leaked = pg_factory.kw["bind"].execution_options(isolation_level="AUTOCOMMIT").connect()
    leaked_pid = leaked.execute(text("SELECT pg_backend_pid()")).scalar_one()
    answers: dict[str, object] = {}
    late_write = in_thread(answers, "late write", lambda: leaked.execute(text(
        "INSERT INTO users (id, username, role, created_at, updated_at) "
        "VALUES ('late', 'late', 'user', now(), now())"
    )))
    count_clients = owner_module._other_clients

    def write_once_the_reset_counts_clients(connection):
        if late_write.ident is None:
            late_write.start()
            _wait_until_waiting_on_a_lock_or_done(
                postgresql_databases.administration_url, leaked_pid, late_write,
            )
        return count_clients(connection)

    monkeypatch.setattr(owner_module, "_other_clients", write_once_the_reset_counts_clients)
    try:
        with pytest.raises(LeakedConnectionError) as refusal:
            postgresql_databases.reset()
    finally:
        stopped = _stop_thread_working_in(
            late_write, postgresql_databases.administration_url, url.database,
        )
        leaked.invalidate()
    assert stopped, "the leaked writer outlived the termination of its database's backends"

    assert re.search(rf"\b{leaked_pid}\b", str(refusal.value))
    assert _contents(url) == baseline


def test_a_connection_closed_while_the_reset_counts_clients_is_no_leak(
    postgresql_databases, postgresql_url, monkeypatch,
):
    """Cell 4: a client the reset counted open, then closed, is seen gone; nothing leaked."""
    engine = create_engine(postgresql_url, poolclass=NullPool)
    closing = engine.connect()
    counts: list[int] = []
    count_clients = owner_module._other_clients

    def close_after_the_first_count(connection):
        counts.append(count_clients(connection))
        closing.close()
        return counts[-1]

    monkeypatch.setattr(owner_module, "_other_clients", close_after_the_first_count)
    try:
        postgresql_databases.reset()
    finally:
        closing.close()
        engine.dispose()
    assert counts[0] == 1


@pytest.mark.parametrize(
    "drift",
    [
        pytest.param("CREATE TABLE stray (id integer)", id="table"),
        pytest.param("ALTER TABLE users ADD COLUMN stray integer", id="column"),
        pytest.param("UPDATE alembic_version SET version_num = 'elsewhere'", id="revision"),
        pytest.param(
            "ALTER TABLE alembic_version RENAME COLUMN version_num TO renamed",
            id="revision-column",
        ),
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
            revision = connection.execute(text(f"SELECT version_num FROM {ALEMBIC_VERSION_TABLE}"))
            assert revision.scalar_one() == migration_head()
    finally:
        engine.dispose()
    owner.reset()


def test_drift_is_found_before_any_row_is_removed(another_run, monkeypatch):
    """Cell 5: the reset checks for drift before it deletes anything."""
    owner = another_run()
    url = owner.worker_url
    engine = create_engine(url, poolclass=NullPool)
    try:
        with sessionmaker(bind=engine).begin() as session:
            session.add(User(id="kept", username="kept"))
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN stray integer"))

        def refuse(_url):
            raise RuntimeError("drop refused")

        monkeypatch.setattr(owner, "drop_database", refuse)
        with pytest.raises(DatabaseDriftError):
            owner.reset()

        with engine.connect() as connection:
            kept = connection.execute(text("SELECT id FROM users WHERE id = 'kept'"))
            assert kept.scalars().all() == ["kept"]
    finally:
        engine.dispose()


def test_drift_committed_while_the_reset_waits_for_its_locks_fails_the_reset(another_run):
    """Cell 5: the drift check runs under the reset's locks, so a late change is still seen."""
    owner = another_run()
    engine = create_engine(owner.worker_url, poolclass=NullPool)
    worker = engine.url.database
    answers: dict[str, object] = {}
    reset = in_thread(answers, "reset", owner.reset)
    try:
        with engine.connect() as drifting:
            drifting.execute(text("ALTER TABLE users ADD COLUMN stray integer"))
            holder = drifting.execute(text("SELECT pg_backend_pid()")).scalar_one()
            reset.start()
            try:
                wait_until_blocked_behind(sessionmaker(bind=engine), holder)
                drifting.commit()
            finally:
                drifting.close()
                if not _stop_thread_working_in(reset, owner.administration_url, worker):
                    pytest.fail("the reset outlived the termination of its database's backends")
    finally:
        engine.dispose()
    assert isinstance(answers.get("reset"), DatabaseDriftError), answers


def _refuse_migrations(monkeypatch) -> None:
    def refuse(_url):
        raise RuntimeError("migration refused")

    monkeypatch.setattr(owner_module, "init_db", refuse)


def _drift_then_fail_the_recreation(owner, monkeypatch) -> BaseException:
    engine = create_engine(owner.worker_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE stray (id integer)"))
    engine.dispose()
    _refuse_migrations(monkeypatch)
    with pytest.raises(DatabaseDriftError) as drift:
        owner.reset()
    return drift.value


def _fail_the_first_migration(owner, monkeypatch) -> BaseException:
    _refuse_migrations(monkeypatch)
    with pytest.raises(WorkerDatabaseUnusableError, match="migration refused") as unusable:
        _ = owner.worker_url
    return unusable.value.__cause__


@pytest.mark.parametrize(
    "make_unusable",
    [
        pytest.param(_drift_then_fail_the_recreation, id="failed-recreation"),
        pytest.param(_fail_the_first_migration, id="failed-first-migration"),
    ],
)
def test_an_unusable_worker_database_fails_every_later_database_fixture(
    another_run, monkeypatch, make_unusable,
):
    """Cell 5: once the worker database cannot be built, every later allocation errors."""
    owner = another_run()
    cause = make_unusable(owner, monkeypatch)
    assert cause is not None

    for later_use in (lambda: owner.worker_url, owner.reset, owner.create_empty_database):
        with pytest.raises(WorkerDatabaseUnusableError, match="migration refused") as unusable:
            later_use()
        assert unusable.value.__cause__ is cause


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
        pytest.param("not a database url", "ArgumentError", id="malformed"),
        pytest.param("sqlite:///probe.db", "must name a PostgreSQL server", id="not-postgresql"),
        pytest.param(
            "postgresql://probe:probe@127.0.0.1:9/probe", "OperationalError", id="unreachable",
        ),
    ],
)
def test_without_a_usable_server_database_tests_fail_and_pure_tests_run(
    environment_with_database_server, replacement, refusal,
):
    """Cell 7: missing configuration fails database tests; none skips."""
    child = subprocess.run(
        _child_pytest("needs_no_database", "needs_a_database"),
        cwd=REPOSITORY_ROOT,
        env=environment_with_database_server(_child_environment(), replacement),
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
