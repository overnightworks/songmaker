# Dependency Injection Refactor

## Problem

7 module-level singletons with `reset_*()` functions:

1. `_session_factory` + `_db_path` in `db/engine.py`
2. `_cached_output_dir` in `config.py`
3. `_trusted_proxies` in `auth.py`
4. `_session_secret` in `auth.py`
5. `_allowed_hosts_cache` in `server.py`
6. `_instance` (GpuQueue) in `gpu_queue.py`
7. `default_registry` in `scoring/pipeline.py`

Consequences:
- No parallel test execution (`pytest-xdist` would cause cross-test contamination)
- Implicit ordering dependencies between resets
- A forgotten reset in one test poisons subsequent tests
- Production code uses module-level globals instead of explicit dependencies

## Design

### AppContext

Single container holding all application state:

```python
@dataclass
class AppContext:
    db: sessionmaker[Session]
    output_dir: Path
    session_secret: bytes
    trusted_proxies: frozenset[str]
    allowed_hosts: tuple[frozenset[str], list[re.Pattern[str]]]
    gpu_queue: GpuQueue
    scorer_registry: ScorerRegistry
```

### Initialization

`create_app()` in `server.py` builds the `AppContext` and stores it on `app.state`:

```python
def create_app(output_dir: Path, project_root: Path) -> FastAPI:
    ctx = AppContext(
        db=init_db(output_dir / DB_FILENAME),
        output_dir=output_dir,
        session_secret=load_session_secret(output_dir),
        # ...
    )
    app.state.ctx = ctx
```

### Access pattern

FastAPI dependencies extract from `request.app.state.ctx`:

```python
def get_db_session(request: Request) -> Session:
    ctx: AppContext = request.app.state.ctx
    session = ctx.db()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

### Test isolation

Each test creates its own `AppContext` with an in-memory SQLite DB:

```python
@pytest.fixture
def ctx(tmp_path):
    return AppContext(
        db=init_db(tmp_path / "test.db"),
        output_dir=tmp_path,
        session_secret=b"test-secret",
        # ...
    )
```

No more `reset_*()` calls. No global state to leak between tests.

### Background thread access

The GPU queue worker thread needs DB access. Pass the session factory via the `AppContext` stored on the queue at creation time, instead of importing `get_session_factory()` from the module.

### Migration strategy

Phase 1 — Add `AppContext` alongside existing singletons, delegate to it:
```python
def get_session_factory() -> sessionmaker[Session]:
    if _app_context is not None:
        return _app_context.db
    # legacy fallback
    if _session_factory is None:
        raise RuntimeError(...)
    return _session_factory
```

Phase 2 — Migrate all callers to use `AppContext` directly via FastAPI dependency injection.

Phase 3 — Remove legacy singletons and `reset_*()` functions.

## Files to change

| Phase | Files | Effort |
|-------|-------|--------|
| 1 | New `app_context.py`, `server.py`, `db/engine.py` | Small |
| 2 | All `*_api.py`, `middleware.py`, `auth.py`, `config.py`, `gpu_queue.py`, `jobs.py` | Large |
| 3 | Remove `reset_*()` from all modules, update all tests | Large |

## Scope

Large. ~500 lines of production changes, ~300 lines of test changes across 20+ files. Best done as a dedicated refactor with no feature work in parallel.

## Prerequisites

- Stuck jobs / graceful shutdown plan (changes `gpu_queue.py` — do that first to avoid merge conflicts)

## Enables

- `pytest-xdist` parallel test execution
- Cleaner test fixtures (no global state leaks)
- Future: multiple app instances in same process (useful for testing)
