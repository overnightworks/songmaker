"""The owner of the PostgreSQL databases a test run uses.

One run and xdist worker gets one database, migrated through production ``init_db()``,
and the reset after every ordinary database test returns it to the state recorded after
migration. Migration tests get additional empty databases. The administration database
is only connected to: it is never migrated, truncated or dropped.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from graphlib import TopologicalSorter
from io import BytesIO

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from psycopg2 import errors as postgresql_errors
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.pool import NullPool

from songmaker_cli.db.engine import MIGRATIONS_DIR, init_db

DATABASE_PREFIX = "songmaker_test"
# PostgreSQL's NAMEDATALEN is 64, so an identifier holds at most 63 bytes.
MAXIMUM_DATABASE_NAME_LENGTH = 63
LOCK_TIMEOUT_MILLISECONDS = 3000
STATEMENT_TIMEOUT_MILLISECONDS = 4 * LOCK_TIMEOUT_MILLISECONDS
DROP_TIMEOUT_MILLISECONDS = 30000
TERMINATION_WAIT_MILLISECONDS = 5000
CONNECT_TIMEOUT_SECONDS = 10
DIAGNOSTIC_BACKEND_LIMIT = 20
# A client that closed its connection may still be listed while its backend exits.
CLOSING_BACKEND_POLL_SECONDS = 0.02
# psycopg2 and libpq take these URL query options over the database named in the path.
DATABASE_SELECTING_OPTIONS = frozenset({"dbname", "database"})
# Alembic's own bookkeeping table; the reset keeps it, since it names the revision.
ALEMBIC_VERSION_TABLE = "alembic_version"
RUN_ID_LENGTH = 12

_SCHEMAS = text(
    "SELECT nspname FROM pg_namespace "
    "WHERE nspname <> 'information_schema' AND nspname NOT LIKE 'pg\\_%' ORDER BY 1"
)
_COLUMNS = text(
    "SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod) "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "LEFT JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped "
    "WHERE c.relkind IN ('r', 'p') "
    "AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%' "
    "ORDER BY 1, 2, 3"
)
_TABLES = text(
    "SELECT c.oid::regclass::text, c.relname FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE c.relkind IN ('r', 'p') "
    "AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%' ORDER BY 1"
)
_FOREIGN_KEYS = text(
    "SELECT conrelid::regclass::text, confrelid::regclass::text "
    "FROM pg_constraint WHERE contype = 'f'"
)
_SEQUENCES = text(
    "SELECT c.oid::regclass::text, s.seqstart, pg_sequence_last_value(c.oid) "
    "FROM pg_sequence s JOIN pg_class c ON c.oid = s.seqrelid ORDER BY 1"
)
_RESTORE_SEQUENCE = text("SELECT setval(CAST(:sequence AS regclass), :value, :is_called)")
_BACKENDS = text(
    "SELECT pid, state, wait_event_type, wait_event, backend_type, "
    "date_trunc('second', now() - xact_start)::text AS transaction_age "
    "FROM pg_stat_activity WHERE datname = :database AND pid <> pg_backend_pid() "
    "ORDER BY pid LIMIT :limit"
)
# A transaction reads pg_stat_activity once and keeps that copy until it is cleared.
_CLEAR_ACTIVITY_SNAPSHOT = text("SELECT pg_stat_clear_snapshot()")
_OTHER_CLIENTS = text(
    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
    "AND backend_type = 'client backend' AND pid <> pg_backend_pid()"
)
_TERMINATE = text(
    "SELECT pg_terminate_backend(pid, :wait) FROM pg_stat_activity "
    "WHERE datname = :database AND pid <> pg_backend_pid()"
)


class DatabaseDriftError(AssertionError):
    """The worker database no longer matches its migrated baseline; nothing was reset."""


class LeakedConnectionError(AssertionError):
    """A connection the test left open outlived it; it was terminated."""


class WorkerDatabaseUnusableError(RuntimeError):
    """The worker database could not be recreated, so no later test may use it."""


@dataclass(frozen=True)
class Baseline:
    """What a freshly migrated worker database holds, recorded right after ``init_db()``."""

    structure: frozenset[tuple[str, ...]]
    tables_referenced_first: tuple[str, ...]
    rows_in_restore_order: tuple[tuple[str, bytes], ...]
    sequences: tuple[tuple[str, int, bool], ...]


@cache
def migration_head() -> str:
    """The single head of the production migration chain."""
    script = ScriptDirectory.from_config(_migrations_config())
    return script.get_current_head()


def _migrations_config() -> Config:
    config = Config()
    config.set_main_option("script_location", MIGRATIONS_DIR)
    return config


def _quote(engine: Engine, name: str) -> str:
    return engine.dialect.identifier_preparer.quote_identifier(name)


def _is_blocked(error: DBAPIError) -> bool:
    blocking = (
        postgresql_errors.LockNotAvailable
        | postgresql_errors.QueryCanceled
        | postgresql_errors.DeadlockDetected
    )
    return isinstance(error.orig, blocking)


def database_name(run_id: str, worker_id: str, suffix: str = "") -> str:
    """The name of a database this run and worker own; refuses one PostgreSQL would cut."""
    parts = [DATABASE_PREFIX, run_id[:RUN_ID_LENGTH], worker_id, suffix]
    name = re.sub(r"[^a-z0-9_]", "_", "_".join(part for part in parts if part).lower())
    if len(name) > MAXIMUM_DATABASE_NAME_LENGTH:
        raise ValueError(f"database name {name!r} exceeds PostgreSQL's identifier length")
    return name


class PostgresqlTestDatabases:
    """Creates, resets and drops the databases of one run and worker, and nothing else."""

    def __init__(
        self,
        administration_url: URL,
        *,
        run_id: str,
        worker_id: str,
    ) -> None:
        selecting = sorted(DATABASE_SELECTING_OPTIONS & set(administration_url.query))
        if selecting:
            raise ValueError(
                f"the administration URL selects its database through the option(s) "
                f"{selecting}; name it in the URL's path only"
            )
        self._administration_url = administration_url
        self._run_id = run_id
        self._worker_id = worker_id
        self._administration = create_engine(
            administration_url, isolation_level="AUTOCOMMIT", poolclass=NullPool,
            connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
        )
        self._worker_name = database_name(run_id, worker_id)
        self._owned: set[str] = set()
        self._empty_count = 0
        self._maintenance: Engine | None = None
        self._baseline: Baseline | None = None
        self._unusable: WorkerDatabaseUnusableError | None = None

    @property
    def administration_url(self) -> URL:
        """The server's administration database, which this owner only connects to."""
        return self._administration_url

    @property
    def worker_url(self) -> URL:
        """The migrated worker database; raises once it could not be created or recreated."""
        self._raise_if_unusable()
        if self._baseline is None:
            try:
                self._create_migrated_worker_database()
            except Exception as failure:  # noqa: BLE001 - any failure makes the database unusable
                raise self._become_unusable(
                    f"{self._worker_name} could not be created and migrated: {failure!r}", failure,
                ) from failure
        return self._database_url(self._worker_name)

    def create_empty_database(self) -> URL:
        """An additional database with nothing in it, for a test that migrates on its own."""
        self._raise_if_unusable()
        self._empty_count += 1
        name = database_name(self._run_id, self._worker_id, f"e{self._empty_count}")
        self._create_database(name)
        return self._database_url(name)

    def drop_database(self, url: URL) -> None:
        """Drop a database this owner created; refuses any other name."""
        name = url.database
        if name not in self._owned:
            raise ValueError(f"{name!r} is not a database of this run and worker")
        with self._administration.connect() as connection:
            connection.execute(text(f"SET statement_timeout = {DROP_TIMEOUT_MILLISECONDS}"))
            connection.execute(
                text(f"DROP DATABASE IF EXISTS {_quote(self._administration, name)} WITH (FORCE)")
            )
        self._owned.discard(name)

    def close(self) -> None:
        """Drop every database this owner created and release its connections."""
        self._dispose_maintenance()
        for name in sorted(self._owned):
            self.drop_database(self._database_url(name))
        self._administration.dispose()

    def reset(self) -> None:
        """Return the worker database to its migrated baseline.

        Drift fails before anything is destroyed, and the database is recreated for the
        next test. A connection left open, in a transaction or not, is reported and
        terminated before any row is restored, and the test fails.
        """
        self._raise_if_unusable()
        try:
            leak = self._reset_once()
        except DatabaseDriftError as drift:
            self._recreate_after(drift)
            raise
        except OperationalError as blocked:
            if not _is_blocked(blocked):
                raise
            self._dispose_maintenance()
            with self._administration.connect() as administration:
                leak = self._report_and_terminate_leaks(
                    f"waited past its {LOCK_TIMEOUT_MILLISECONDS} ms lock timeout on a "
                    "transaction the test left open",
                    administration,
                )
            try:
                self._reset_once()
            except (OperationalError, DatabaseDriftError) as still_failing:
                self._recreate_after(still_failing)
            raise leak from blocked
        if leak is not None:
            raise leak

    def _terminate_lingering_clients(self, connection: Connection) -> LeakedConnectionError | None:
        """Give closing connections time to end, then terminate every other client left.

        It runs on the reset's connection while the reset holds its locks, so a client still
        connected can no longer write a table, and it is gone before any row is restored.
        """
        deadline = time.monotonic() + LOCK_TIMEOUT_MILLISECONDS / 1000
        while _other_clients(connection):
            if time.monotonic() >= deadline:
                return self._report_and_terminate_leaks(
                    f"found a connection the test left open {LOCK_TIMEOUT_MILLISECONDS} ms "
                    "after it ended",
                    connection,
                )
            time.sleep(CLOSING_BACKEND_POLL_SECONDS)
        return None

    def _report_and_terminate_leaks(
        self, finding: str, connection: Connection,
    ) -> LeakedConnectionError:
        backends = self._backends(connection)
        self._terminate_backends(connection)
        return LeakedConnectionError(
            f"The reset of {self._worker_name} {finding}; it was terminated.\n"
            f"Open backends (pid, state, wait type, wait event, backend, transaction age):\n"
            + "\n".join(str(backend) for backend in backends)
        )

    def _reset_once(self) -> LeakedConnectionError | None:
        baseline = self._baseline
        if baseline is None:
            return None
        with self._maintenance_engine().connect() as connection, connection.begin():
            connection.execute(text(f"SET LOCAL lock_timeout = {LOCK_TIMEOUT_MILLISECONDS}"))
            connection.execute(
                text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MILLISECONDS}")
            )
            self._lock_and_raise_on_drift(connection, baseline)
            leak = self._terminate_lingering_clients(connection)
            for table in reversed(baseline.tables_referenced_first):
                connection.execute(text(f"DELETE FROM {table}"))
            cursor = connection.connection.driver_connection.cursor()
            for table, rows in baseline.rows_in_restore_order:
                cursor.copy_expert(f"COPY {table} FROM STDIN", BytesIO(rows))
            for sequence, value, is_called in baseline.sequences:
                connection.execute(
                    _RESTORE_SEQUENCE,
                    {"sequence": sequence, "value": value, "is_called": is_called},
                )
        return leak

    def _lock_and_raise_on_drift(self, connection: Connection, baseline: Baseline) -> None:
        """Lock every table, then compare; a change committed while the lock waited is seen.

        The exclusive lock also makes a transaction the test left open block the reset, as
        TRUNCATE would; on 29 small tables a DELETE per table measured faster than one
        TRUNCATE, which replaces every table's files. A table or column the check cannot
        read is drift too.
        """
        tables = ", ".join((*baseline.tables_referenced_first, ALEMBIC_VERSION_TABLE))
        try:
            connection.execute(text(f"LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE"))
            self._raise_on_drift(connection, baseline)
        except DBAPIError as unreadable:
            if _is_blocked(unreadable):
                raise
            raise DatabaseDriftError(
                f"{self._worker_name} could not be checked against its migrated schema: "
                f"{unreadable.orig!r}"
            ) from unreadable

    def _raise_on_drift(self, connection: Connection, baseline: Baseline) -> None:
        structure = _structure(connection)
        if structure != baseline.structure:
            added = sorted(structure - baseline.structure)[:10]
            missing = sorted(baseline.structure - structure)[:10]
            raise DatabaseDriftError(
                f"{self._worker_name} no longer matches its migrated schema; "
                f"added: {added}, missing: {missing}"
            )
        revisions = set(MigrationContext.configure(connection).get_current_heads())
        head = migration_head()
        if revisions != {head}:
            raise DatabaseDriftError(
                f"{self._worker_name} is at revision {sorted(revisions)}, not at head {head}"
            )

    def _recreate_after(self, cause: BaseException) -> None:
        self._dispose_maintenance()
        self._baseline = None
        try:
            self.drop_database(self._database_url(self._worker_name))
            self._create_migrated_worker_database()
        except Exception as failure:  # noqa: BLE001 - any failure makes the database unusable
            self._become_unusable(
                f"{self._worker_name} could not be recreated after {cause!r}: {failure!r}", cause,
            )

    def _become_unusable(
        self, problem: str, cause: BaseException,
    ) -> WorkerDatabaseUnusableError:
        unusable = WorkerDatabaseUnusableError(problem)
        unusable.__cause__ = cause
        self._unusable = unusable
        return unusable

    def _raise_if_unusable(self) -> None:
        if self._unusable is not None:
            raise self._unusable

    def _create_migrated_worker_database(self) -> None:
        self._create_database(self._worker_name)
        url = self._database_url(self._worker_name)
        init_db(url).kw["bind"].dispose()
        with self._maintenance_engine().connect() as connection:
            self._baseline = _record_baseline(connection)

    def _create_database(self, name: str) -> None:
        with self._administration.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {_quote(self._administration, name)}"))
        self._owned.add(name)

    def _backends(self, connection: Connection) -> list[tuple[object, ...]]:
        rows = connection.execute(
            _BACKENDS, {"database": self._worker_name, "limit": DIAGNOSTIC_BACKEND_LIMIT},
        )
        return [tuple(row) for row in rows]

    def _terminate_backends(self, connection: Connection) -> None:
        connection.execute(
            _TERMINATE, {"database": self._worker_name, "wait": TERMINATION_WAIT_MILLISECONDS},
        )

    def _maintenance_engine(self) -> Engine:
        if self._maintenance is None:
            self._maintenance = create_engine(
                self._database_url(self._worker_name), pool_size=1, max_overflow=0,
                pool_pre_ping=True, connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
            )
        return self._maintenance

    def _dispose_maintenance(self) -> None:
        if self._maintenance is not None:
            self._maintenance.dispose()
            self._maintenance = None

    def _database_url(self, name: str) -> URL:
        return self._administration_url.set(database=name)


def _other_clients(connection: Connection) -> int:
    connection.execute(_CLEAR_ACTIVITY_SNAPSHOT)
    return connection.execute(_OTHER_CLIENTS).scalar_one()


def _structure(connection: Connection) -> frozenset[tuple[str, ...]]:
    schemas = {("schema", name) for (name,) in connection.execute(_SCHEMAS)}
    columns = {
        ("column", schema, table, column or "", column_type or "")
        for schema, table, column, column_type in connection.execute(_COLUMNS)
    }
    return frozenset(schemas | columns)


def _record_baseline(connection: Connection) -> Baseline:
    tables = [
        qualified for qualified, name in connection.execute(_TABLES)
        if name != ALEMBIC_VERSION_TABLE
    ]
    cursor = connection.connection.driver_connection.cursor()
    rows: dict[str, bytes] = {}
    for table in tables:
        buffer = BytesIO()
        cursor.copy_expert(f"COPY {table} TO STDOUT", buffer)
        if buffer.getvalue():
            rows[table] = buffer.getvalue()
    sequences = tuple(
        (name, start if last is None else last, last is not None)
        for name, start, last in connection.execute(_SEQUENCES)
    )
    tables_in_order = tuple(_dependency_order(tables, connection.execute(_FOREIGN_KEYS)))
    return Baseline(
        structure=_structure(connection),
        tables_referenced_first=tables_in_order,
        rows_in_restore_order=tuple(
            (table, rows[table]) for table in tables_in_order if table in rows
        ),
        sequences=sequences,
    )


def _dependency_order(
    tables: Iterable[str], foreign_keys: Iterable[tuple[str, str]],
) -> list[str]:
    """Tables ordered so every referenced table comes before the tables referencing it."""
    wanted = set(tables)
    graph: dict[str, set[str]] = {table: set() for table in wanted}
    for referencing, referenced in foreign_keys:
        if referencing in wanted and referenced in wanted and referencing != referenced:
            graph[referencing].add(referenced)
    return list(TopologicalSorter(graph).static_order())
