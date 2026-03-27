# Migration: SQLite → PostgreSQL

> **Status: NOT STARTED** — prerequisite for concurrent write load and multi-process deployment.
> **Depends on: Phase 0 (feature flag infrastructure)**

## Problem

SQLite serializes all writes. Under concurrent users, every `session.commit()` contends on a single file lock. `BEGIN IMMEDIATE` transactions (used for TOCTOU prevention in rate limiting and slug generation) are SQLite-specific. The single-file DB can't be shared across containers without NFS.

## Goal

Replace SQLite with PostgreSQL while preserving all existing behavior. The same codebase should work with both backends during migration (controlled by `DATABASE_URL`).

## Complete SQLite-Specific Pattern Inventory

Every item below MUST be replaced or guarded by dialect. File:line references are exact.

### `engine.py` — DB initialization

| Pattern | Line | SQLite behavior | PostgreSQL equivalent |
|---------|------|----------------|----------------------|
| `PRAGMA journal_mode=WAL` | 24 | Write-ahead logging | Default MVCC (no config needed) |
| `PRAGMA foreign_keys=ON` | 25 | Enable FK enforcement | Default (with constraints defined) |
| `connect_args={"timeout": 30}` | 64 | SQLite busy timeout | Not needed — use pool_timeout instead |
| `connect_args={"timeout": 30}` | 77 | Same for test DB | Same |
| `_restrict_permissions()` | 84-90 | chmod 0o600 on .db, -wal, -shm | Not needed (pg_hba.conf handles auth) |
| `StaticPool` | 78 | Test DB uses static pool | Use `StaticPool` for tests or `create_engine(url)` |

**Implementation**:
```python
def init_db(db_url: str) -> sessionmaker[Session]:
    is_sqlite = db_url.startswith("sqlite")
    kwargs: dict[str, Any] = {}
    if is_sqlite:
        kwargs["connect_args"] = {"timeout": 30}
    else:
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 10
        kwargs["pool_pre_ping"] = True
    engine = create_engine(db_url, **kwargs)
    if is_sqlite:
        event.listen(engine, "connect", _enable_sqlite_pragmas)
    _run_migrations(engine)
    if is_sqlite:
        _restrict_permissions(Path(db_url.replace("sqlite:///", "")))
    return sessionmaker(bind=engine)
```

### `api_helpers.py` — Atomic transactions

| Pattern | Line | SQLite behavior | PostgreSQL equivalent |
|---------|------|----------------|----------------------|
| `session.commit(); session.execute(text("BEGIN IMMEDIATE"))` | 61-62 | Exclusive write lock for TOCTOU prevention | `SELECT ... FOR UPDATE` or serializable isolation |
| Same pattern | 101-102 | Atomic slug collision detection | `INSERT ... ON CONFLICT` or advisory lock |

**Implementation for `create_job_with_rate_limit()` (line 43-81)**:

```python
def create_job_with_rate_limit(session, user, job_type):
    session.commit()  # flush auth-layer mutations (both dialects)

    dialect = session.bind.dialect.name
    if dialect == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
    else:
        # PostgreSQL: use serializable isolation for this transaction
        session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))

    # ... rate limit checks (unchanged) ...
    # ... create_job (unchanged) ...
```

**Implementation for `unique_album_id()` (line 99-108)**:

```python
def unique_album_id(session, title):
    session.commit()
    dialect = session.bind.dialect.name
    if dialect == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
    else:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
    # ... collision loop (unchanged) ...
```

### `db/migrations/env.py` — Alembic configuration

| Pattern | Line | Current | Required |
|---------|------|---------|----------|
| `SONGMAKER_DB_URL` env var | 29 | Falls back to SQLite | Unify to `DATABASE_URL` (same as engine.py) |
| `_resolve_db_url()` | 25-33 | Custom resolution chain | Use `DATABASE_URL` with same fallback |
| Offline migration mode | 36-45 | Works for SQLite | Works for PostgreSQL (no change) |

**Implementation**: Replace `_resolve_db_url()` line 25-33:
```python
def _resolve_db_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    return os.environ.get("DATABASE_URL", f"sqlite:///{Path.cwd() / '_output' / 'songmaker.db'}")
```

### `db/queries/jobs.py` — SQLite-specific SQL

| Pattern | Line | SQLite behavior | PostgreSQL equivalent |
|---------|------|----------------|----------------------|
| `func.julianday()` | 153-155 | SQLite date function for duration calc | `EXTRACT(EPOCH FROM ...)` |

**Implementation for `job_duration_stats()` (line 141-158)**:

```python
def job_duration_stats(session):
    dialect = session.bind.dialect.name
    if dialect == "sqlite":
        duration_expr = (func.julianday(Job.completed_at) - func.julianday(Job.started_at)) * 86400.0
    else:
        duration_expr = func.extract("epoch", Job.completed_at - Job.started_at)
    # ... rest unchanged, use duration_expr ...
```

### `server.py` — Worker guard

| Pattern | Line | Current | Required |
|---------|------|---------|----------|
| `UVICORN_WORKERS > 1` raises ValueError | 742-747 | Blocks multi-worker for SQLite | Allow multi-worker when `DATABASE_URL` is non-SQLite AND `REDIS_URL` is set |

## Steps

### Phase 1: Abstraction layer (Phase 0 covers most of this)

- [ ] `DATABASE_URL` env var detection in `engine.py` (Phase 0 implements this)
- [ ] Dialect-conditional PRAGMAs, connect_args, pool config (Phase 0)
- [ ] Dialect-conditional file permissions (Phase 0)
- [ ] Update `alembic/env.py` to use `DATABASE_URL` instead of `SONGMAKER_DB_URL`

### Phase 2: Replace SQLite-specific patterns

- [ ] `api_helpers.py:61-62` — Replace `BEGIN IMMEDIATE` with dialect-conditional serializable isolation
- [ ] `api_helpers.py:101-102` — Same for `unique_album_id()`
- [ ] Create `_begin_exclusive(session)` helper that picks the right strategy per dialect:
  ```python
  def _begin_exclusive(session: Session) -> None:
      if session.bind.dialect.name == "sqlite":
          session.execute(text("BEGIN IMMEDIATE"))
      else:
          session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
  ```
- [ ] `db/queries/jobs.py:153-155` — Replace `func.julianday()` with dialect-conditional expression

### Phase 3: Alembic migration rework

- [ ] Keep existing SQLite migrations (backwards compat)
- [ ] Generate fresh baseline migration for PostgreSQL: `alembic revision --autogenerate -m "baseline_postgresql"`
- [ ] Test: fresh PostgreSQL DB → `alembic upgrade head` → verify all tables
- [ ] Test: run full test suite against PostgreSQL
- [ ] `env.py`: use `DATABASE_URL` (already done in Phase 1)

### Phase 4: Connection pooling

- [ ] Configure `QueuePool` for PostgreSQL (pool_size=5, max_overflow=10, pool_recycle=3600)
- [ ] Add `pool_pre_ping=True` for connection health checking
- [ ] Test under concurrent load: 10 simultaneous requests, verify no connection exhaustion
- [ ] Test: connection pool recovery after PostgreSQL restart

### Phase 5: Data migration tool

- [ ] Create `scripts/migrate_sqlite_to_postgres.py`
- [ ] Read all tables from SQLite, bulk insert into PostgreSQL
- [ ] Table order (respects FK constraints): users → albums → songs → versions → generations → scores → ratings → generation_presets → jobs → user_sessions → login_attempts → audit_log
- [ ] Preserve UUIDs (TEXT type in both — no conversion needed)
- [ ] Preserve timestamps (SQLite stores as ISO strings, PostgreSQL wants TIMESTAMP — handle conversion)
- [ ] Idempotent: truncate-then-insert per table (safer than upsert for initial migration)
- [ ] Validation: count rows per table in both DBs after migration

### Phase 6: Docker Compose

- [ ] Add `postgres:16-alpine` service with persistent volume
- [ ] Init script: create database and user
- [ ] `DATABASE_URL=postgresql://songmaker:password@postgres:5432/songmaker`
- [ ] Health check: `pg_isready -U songmaker`
- [ ] Document backup strategy: `pg_dump` via cron

## Design Decisions

### UUID vs serial primary keys
Current: UUID strings as TEXT. Keep as TEXT — avoids model changes, works identically. PostgreSQL native `UUID` type is faster for indexing but requires model changes. Revisit only if query performance on ID lookups becomes measurable.

### Connection pooling strategy
- API requests: `QueuePool` (default for PostgreSQL in SQLAlchemy)
- `NullPool` for SQLite (current behavior, single-file DB)
- No PgBouncer needed at current scale

### Transaction isolation for TOCTOU
- Default: READ COMMITTED (PostgreSQL default)
- Rate limit checks: SERIALIZABLE for the specific transaction only
- This matches the behavior of SQLite's `BEGIN IMMEDIATE` — exclusive write lock

### Timestamp handling
SQLite stores datetime as ISO 8601 strings. PostgreSQL uses native TIMESTAMP. SQLAlchemy handles the conversion transparently for ORM operations. The migration script must convert strings to timestamps explicitly.

## Testing

- All existing tests must pass against both SQLite and PostgreSQL
- `conftest.py`: parameterize DB fixture with `TEST_DB_BACKEND=sqlite|postgresql` env var
- CI: run suite against SQLite (fast, default) and PostgreSQL (Docker service, separate job)
- New test: concurrent write stress test (10 threads hitting `create_job_with_rate_limit`)
- New test: verify `job_duration_stats()` returns correct values on both dialects

## Migration Safety

- Both backends supported simultaneously via `DATABASE_URL`
- Default remains SQLite (no breaking change for existing deployments)
- Run both in parallel during transition, compare query results
