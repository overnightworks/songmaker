"""The owner of the PostgreSQL databases a test run uses.

One run and xdist worker gets one database, migrated through production ``init_db()``,
and the reset after every ordinary database test returns it to the state recorded after
migration. Migration tests get additional empty databases. The administration database
is only connected to: it is never migrated, truncated or dropped.
"""

from __future__ import annotations

import re
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
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

from songmaker_cli.db.engine import MIGRATIONS_DIR, init_db

DATABASE_PREFIX = "songmaker_test"
# PostgreSQL's NAMEDATALEN is 64, so an identifier holds at most 63 bytes.
MAXIMUM_DATABASE_NAME_LENGTH = 63
LOCK_TIMEOUT_MILLISECONDS = 3000
STATEMENT_TIMEOUT_MILLISECONDS = 4 * LOCK_TIMEOUT_MILLISECONDS
DROP_TIMEOUT_MILLISECONDS = 30000
TERMINATION_WAIT_MILLISECONDS = 5000
DIAGNOSTIC_BACKEND_LIMIT = 20
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
    "FROM pg_stat_activity WHERE datname = :database ORDER BY pid LIMIT :limit"
)
_TERMINATE = text(
    "SELECT pg_terminate_backend(pid, :wait) FROM pg_stat_activity "
    "WHERE datname = :database AND pid <> pg_backend_pid()"
)


class DatabaseDriftError(AssertionError):
    """The worker database no longer matches its migrated baseline; nothing was reset."""


class LeakedConnectionError(AssertionError):
    """A connection the test left open blocked the reset; it was terminated."""


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


def _is_blocked(error: OperationalError) -> bool:
    blocking = postgresql_errors.LockNotAvailable | postgresql_errors.QueryCanceled
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
        self._administration_url = administration_url
        self._run_id = run_id
        self._worker_id = worker_id
        self._administration = create_engine(
            administration_url, isolation_level="AUTOCOMMIT", poolclass=NullPool,
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
        """The migrated worker database; raises once it could not be recreated."""
        if self._unusable is not None:
            raise self._unusable
        if self._baseline is None:
            self._create_migrated_worker_database()
        return self._database_url(self._worker_name)

    def create_empty_database(self) -> URL:
        """An additional database with nothing in it, for a test that migrates on its own."""
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
        next test. A connection left open is reported, terminated and the reset retried.
        """
        if self._unusable is not None:
            raise self._unusable
        try:
            self._reset_once()
        except DatabaseDriftError as drift:
            self._recreate_after(drift)
            raise
        except OperationalError as blocked:
            if not _is_blocked(blocked):
                raise
            self._report_and_terminate_leaks(blocked)

    def _report_and_terminate_leaks(self, blocked: OperationalError) -> None:
        self._dispose_maintenance()
        backends = self._backends()
        self._terminate_backends()
        try:
            self._reset_once()
        except (OperationalError, DatabaseDriftError) as still_failing:
            self._recreate_after(still_failing)
        raise LeakedConnectionError(
            f"The reset of {self._worker_name} waited past its {LOCK_TIMEOUT_MILLISECONDS} ms "
            f"lock timeout on a connection the test left open; it was terminated.\n"
            f"Open backends (pid, state, wait type, wait event, backend, transaction age):\n"
            + "\n".join(str(backend) for backend in backends)
        ) from blocked

    def _reset_once(self) -> None:
        baseline = self._baseline
        if baseline is None:
            return
        with self._maintenance_engine().connect() as connection, connection.begin():
            connection.execute(text(f"SET LOCAL lock_timeout = {LOCK_TIMEOUT_MILLISECONDS}"))
            connection.execute(
                text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MILLISECONDS}")
            )
            self._raise_on_drift(connection, baseline)
            # The exclusive lock makes a transaction the test left open block the reset,
            # as TRUNCATE would; on 29 small tables a DELETE per table measured faster
            # than one TRUNCATE, which replaces every table's files.
            tables = ", ".join(baseline.tables_referenced_first)
            connection.execute(text(f"LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE"))
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

    def _raise_on_drift(self, connection: Connection, baseline: Baseline) -> None:
        revisions = set(MigrationContext.configure(connection).get_current_heads())
        head = migration_head()
        if revisions != {head}:
            raise DatabaseDriftError(
                f"{self._worker_name} is at revision {sorted(revisions)}, not at head {head}"
            )
        structure = _structure(connection)
        if structure != baseline.structure:
            added = sorted(structure - baseline.structure)[:10]
            missing = sorted(baseline.structure - structure)[:10]
            raise DatabaseDriftError(
                f"{self._worker_name} no longer matches its migrated schema; "
                f"added: {added}, missing: {missing}"
            )

    def _recreate_after(self, cause: BaseException) -> None:
        self._dispose_maintenance()
        self._baseline = None
        try:
            self.drop_database(self._database_url(self._worker_name))
            self._create_migrated_worker_database()
        except Exception as failure:  # noqa: BLE001 - any failure makes the database unusable
            unusable = WorkerDatabaseUnusableError(
                f"{self._worker_name} could not be recreated after {cause!r}: {failure!r}"
            )
            unusable.__cause__ = cause
            self._unusable = unusable

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

    def _backends(self) -> list[tuple[object, ...]]:
        with self._administration.connect() as connection:
            rows = connection.execute(
                _BACKENDS, {"database": self._worker_name, "limit": DIAGNOSTIC_BACKEND_LIMIT},
            )
            return [tuple(row) for row in rows]

    def _terminate_backends(self) -> None:
        with self._administration.connect() as connection:
            connection.execute(
                _TERMINATE,
                {"database": self._worker_name, "wait": TERMINATION_WAIT_MILLISECONDS},
            )

    def _maintenance_engine(self) -> Engine:
        if self._maintenance is None:
            self._maintenance = create_engine(
                self._database_url(self._worker_name), pool_size=1, max_overflow=0,
                pool_pre_ping=True,
            )
        return self._maintenance

    def _dispose_maintenance(self) -> None:
        if self._maintenance is not None:
            self._maintenance.dispose()
            self._maintenance = None

    def _database_url(self, name: str) -> URL:
        return self._administration_url.set(database=name)


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
