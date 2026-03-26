# Dependency Injection Refactor

## Problem

7 module-level singletons with `reset_*()` functions block parallel tests and leak state between test runs. Each requires explicit teardown — forgetting one poisons subsequent tests.

## Goal

Replace all 7 singletons with a single `AppContext` dataclass. No backwards compatibility — rip out the old globals completely. Tests create their own `AppContext` per fixture.

## AppContext

File: `src/songmaker_cli/app_context.py` (already created)

```python
@dataclass
class AppContext:
    db: sessionmaker[Session]
    output_dir: Path
    session_secret: bytes
    trusted_proxies: frozenset[str]
    allowed_hosts_exact: frozenset[str]
    allowed_hosts_patterns: list[re.Pattern[str]]
    gpu_queue: GpuQueue | None = None
```

## Singletons to remove

| Singleton | Location | Callers |
|-----------|----------|---------|
| `_session_factory` + `_db_path` | `db/engine.py` | FastAPI deps, gpu_queue threads, jobs threads, server startup, main.py escape hatches |
| `_cached_output_dir` | `config.py` | FastAPI endpoints (song/album/generation delete), jobs threads, server startup |
| `_trusted_proxies` | `auth.py` | `get_client_ip()` callers: middleware, auth_api, server middleware |
| `_session_secret` | `auth.py` | `sign_session_id()`, `verify_session_cookie()`, `generate_csrf_token()`, `verify_csrf_token()` |
| `_allowed_hosts_cache` | `server.py` | `CsrfOriginMiddleware` via `_is_allowed_host()` |
| `_instance` (GpuQueue) | `gpu_queue.py` | `generation_api.py` endpoints, server lifespan shutdown |
| `default_registry` | `scoring/pipeline.py` | Leave as-is — immutable after loading, tests already use separate registries |

## Critical: background thread access

`get_session_factory()` and `get_output_dir()` are called from the GPU queue worker thread (via `jobs.py`), which has NO access to FastAPI `Request`. These must be passed explicitly:

- **GpuQueue**: receives `db_factory` in `__init__()`, uses `self._db_factory` in `_recover_stale_jobs()`, `_periodic_cleanup()`, `_fail_job()`
- **Job functions**: receive `db_factory` and `output_dir` as parameters. Endpoints pass these from `ctx` at submit time:
  ```python
  ctx.gpu_queue.submit(job_id, "generate", run_generation_job,
      args=(job_id, song_id, version_id, count),
      kwargs={"db_factory": ctx.db, "output_dir": ctx.output_dir})
  ```

## Auth function signature changes

All auth functions that use `_session_secret` or `_trusted_proxies` must take them as parameters instead of reading globals:

| Function | Current | After |
|----------|---------|-------|
| `get_client_ip(host, xff)` | reads `get_trusted_proxies()` | `get_client_ip(host, xff, trusted_proxies)` |
| `sign_session_id(sid)` | reads `_get_session_secret()` | `sign_session_id(sid, secret)` |
| `verify_session_cookie(cookie)` | reads `_get_session_secret()` | `verify_session_cookie(cookie, secret)` |
| `generate_csrf_token(sid)` | reads `_get_session_secret()` | `generate_csrf_token(sid, secret)` |
| `verify_csrf_token(token, sid)` | calls `generate_csrf_token()` | `verify_csrf_token(token, sid, secret)` |

Remove: `_get_session_secret()`, `reset_session_secret()`, `get_trusted_proxies()`, `reset_trusted_proxies()`, `_session_secret`, `_trusted_proxies`.

`ensure_session_secret()` stays — it generates/loads the secret at startup. Returns the secret string which gets stored in AppContext.

## Server startup changes

`create_app()` builds the AppContext:

```python
def create_app(output_dir, project_root, db_factory=None, session_secret=None, ...):
    ctx = AppContext(
        db=db_factory or init_db(output_dir / DB_FILENAME),
        output_dir=output_dir,
        session_secret=(session_secret or ensure_session_secret(output_dir)).encode(),
        trusted_proxies=parse_trusted_proxies(),
        allowed_hosts_exact=exact, allowed_hosts_patterns=patterns,
        gpu_queue=GpuQueue(db_factory),
    )
    app.state.ctx = ctx
    ctx.gpu_queue.start()
```

`run_server()` calls `create_app()` (no longer calls `init_db()`, `set_output_dir()`, or `ensure_session_secret()` separately — all handled inside `create_app()`).

## FastAPI dependency chain

Replace `db/engine.py:get_db_session()` with a dep that pulls from AppContext:

```python
def get_app_context(request: Request) -> AppContext:
    return request.app.state.ctx

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

These can live in `app_context.py` or stay in `db/engine.py` — your call.

## Middleware changes

All middleware classes access `request.app.state.ctx` (or `scope["app"].state.ctx` for raw ASGI middleware):

- `SecurityHeadersMiddleware`: uses `ctx.trusted_proxies` instead of `get_trusted_proxies()`
- `CsrfTokenMiddleware`: uses `ctx.session_secret` for `verify_session_cookie()` and `verify_csrf_token()`
- `CsrfOriginMiddleware`: uses `ctx.allowed_hosts_exact` and `ctx.allowed_hosts_patterns` instead of `_get_allowed_hosts()`
- `IpRateLimitMiddleware`: uses `ctx.trusted_proxies` via `get_client_ip()`
- `AccessLogMiddleware`: uses `ctx.trusted_proxies` via `get_client_ip()`

## What stays in db/engine.py

`init_db(path)` stays — it creates the engine and returns a `sessionmaker`. But it no longer stores globals. It just returns the factory.

`get_session_factory()` and `reset_engine()` are removed.

## What stays in config.py

`build_ace_config()`, `load_generation_defaults()`, `save_generation_defaults()` stay but take `output_dir` as parameter instead of calling `get_output_dir()`.

`set_output_dir()`, `get_output_dir()`, `reset_output_dir()` are removed.

## What stays in server.py

`_allowed_hosts_cache`, `reset_allowed_hosts_cache()`, `_get_allowed_hosts()`, `_is_allowed_host()` are removed. The parsing logic moves to a helper `parse_allowed_hosts()` that returns `(exact, patterns)` — called once at startup.

## main.py escape hatches

`reset-password` and `list-users` CLI commands bypass the API. They call `init_db()` directly (which now just returns a factory without storing globals). No AppContext needed — they don't use FastAPI.

## Test fixture pattern

```python
@pytest.fixture()
def app_context(tmp_path):
    factory = init_db(tmp_path / "test.db")
    return AppContext(
        db=factory,
        output_dir=tmp_path / "_output",
        session_secret=b"test-secret-at-least-32-characters-long!!",
        trusted_proxies=frozenset(),
    )

@pytest.fixture()
def client(app_context):
    app = create_app_from_context(app_context, project_root=...)
    return TestClient(app)
```

No more `reset_engine()`, `reset_session_secret()`, `reset_trusted_proxies()`, `reset_output_dir()`, `reset_allowed_hosts_cache()`, `reset_gpu_queue()` in any test.

The autouse `_set_session_secret` fixture in `conftest.py` is removed entirely.

## Files to change

| File | Changes |
|------|---------|
| `app_context.py` | Already exists, may need minor tweaks |
| `db/engine.py` | Remove `_session_factory`, `_db_path`, `get_session_factory()`, `reset_engine()`, `get_db_session()`. Keep `init_db()` returning factory. |
| `config.py` | Remove `_cached_output_dir`, `get_output_dir()`, `set_output_dir()`, `reset_output_dir()`. Functions take `output_dir` param. |
| `auth.py` | Remove `_session_secret`, `_trusted_proxies`, `_get_session_secret()`, `reset_session_secret()`, `get_trusted_proxies()`, `reset_trusted_proxies()`. Auth functions take secret/proxies as params. |
| `server.py` | Build AppContext in `create_app()`. Remove `_allowed_hosts_cache`, `reset_allowed_hosts_cache()`. Middleware uses `ctx`. |
| `gpu_queue.py` | `GpuQueue.__init__(db_factory)`. Remove `_instance`, `get_gpu_queue()`, `reset_gpu_queue()`. |
| `jobs.py` | `run_generation_job(..., db_factory, output_dir)`, `run_scoring_job(..., db_factory, output_dir)`. |
| `middleware.py` | `get_current_user()` gets secret from `ctx` for `verify_session_cookie()`. |
| `generation_api.py` | Get `ctx` from dep, submit with `db_factory`+`output_dir` in kwargs. |
| `song_api.py` | Get `output_dir` from ctx dep instead of `get_output_dir()`. |
| `album_api.py` | Get `output_dir` from ctx dep instead of `get_output_dir()`. |
| `chat_api.py` | Minor — dep chain update only. |
| `admin_api.py` | Minor — dep chain update only. |
| `auth_api.py` | Get secret/proxies from ctx for `sign_session_id()`, `get_client_ip()`. |
| `settings_api.py` | Minor — dep chain update only. |
| `api_helpers.py` | Minor — dep chain update only. |
| All test files | Replace `reset_*()` with AppContext fixtures. ~20 files. |
| `conftest.py` | Remove autouse `_set_session_secret`. Add `app_context` fixture. |

## Scope

Large. ~600 lines production, ~400 lines tests across 25+ files. No backwards compatibility — clean break.

## Order of operations

1. Update `auth.py` — add params to auth functions, remove globals
2. Update `db/engine.py` — remove globals, keep `init_db()` pure
3. Update `config.py` — remove globals, add `output_dir` params
4. Update `gpu_queue.py` — constructor injection, remove singleton
5. Update `jobs.py` — parameter injection
6. Update `server.py` — build AppContext, update middleware
7. Update `middleware.py` — pass secret from ctx
8. Update all `*_api.py` — use new deps
9. Update `conftest.py` + all tests — AppContext fixtures
10. Run checks, fix failures
