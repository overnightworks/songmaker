# Phase 2 Sub-plan — Control plane (registration + Redis state)

> Concrete implementation plan for Phase 2 of [acestep-worker-pool.md](acestep-worker-pool.md). Written after exploration of the existing songmaker_cli patterns. Read this end-to-end before starting; it captures decisions that aren't in the parent plan.

## State at start of Phase 2

- **Branch:** `feat/acestep-worker-pool` (Phase 1 committed as `c416194`, pushed to origin)
- **Phase 1 shipped:** standalone `acestep_worker` peer package + Dockerfile + compose service. 100% test coverage on 10 modules, 121 tests. Container builds clean, app constructs end-to-end with all 8 worker endpoints registered.
- **Worker is running standalone** but not yet known to the web container. The music-worker still owns the legacy `acestep_manager.py` flow, untouched.
- **`MODEL_CONFIG_PATHS` already lives at** [src/acestep_engine/constants.py](../src/acestep_engine/constants.py); `songmaker_cli/constants.py` re-exports it.

## Phase 2 goal (recap)

The web container becomes the control plane:
- Workers `POST /api/internal/workers/register` once on startup → upsert into a new `acestep_workers` PG table (identity only)
- Workers also write ephemeral state directly to Redis with 15s TTL (already done in Phase 1's `heartbeat.py`)
- Admin UI gets new endpoints: `GET /api/admin/workers`, `GET /api/admin/registry`, plus proxies for load/evict
- Trust boundary documented in `docs/security.md` **in this same phase** (promoted from Phase 6)

The web container does **not** start any workers, generate anything, or touch ACE-Step. It's the control plane only.

## Architectural decisions made during exploration

These are the calls I'd make. If you disagree with any, that's the place to push back before implementation.

### D1. Async Redis client: reuse `arq_pool`, don't add a new one

The web container already has an async Redis client via `get_arq_pool()` ([arq_pool.py:38](../src/songmaker_cli/arq_pool.py#L38)). It's an `ArqRedis` instance which inherits from `redis.asyncio.Redis`, so it has all the standard methods (`get`, `set`, `incr`, `decr`, `delete`, `exists`).

The existing `acestep_status` admin endpoint already uses `pool.get(...)` for Redis reads ([admin_api.py:304-324](../src/songmaker_cli/admin_api.py#L304-L324)). I'll follow that pattern.

**Decision:** new admin endpoints will be `async def`, take `pool = Depends(get_arq_pool_dep)` (see D2), and use it for Redis reads. No new client added to `AppContext`.

### D2. New tiny dependency `get_arq_pool_dep`

`get_arq_pool()` is a sync function that returns the global `_pool` singleton. To use it as a FastAPI dependency, wrap it:

```python
def get_arq_pool_dep() -> ArqRedis:
    return get_arq_pool()
```

Lives in `arq_pool.py`. One line. The wrapper exists so tests can override it via `app.dependency_overrides`.

### D3. `acestep_workers` table — no `ShareMixin`, identity only

```python
class AceStepWorker(Base):
    __tablename__ = "acestep_workers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    gpu_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vram_total_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)
    last_register_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow, onupdate=_utcnow)
```

`String(50)` for the ID is generous (worker IDs like `acestep-worker-0` are short; 50 leaves headroom for `acestep-worker-gpu1.cluster.internal` style names if it ever matters).

No `ShareMixin` — workers aren't user-shareable.
No relationships — workers don't reference other tables.

### D4. Redis read helpers live in a new file `src/songmaker_cli/acestep_state.py`

Not in `redis_client.py` (which is the sync session cache, different concern), not in `arq_pool.py` (which is the connection pool, different concern). New file:

```python
# src/songmaker_cli/acestep_state.py
from __future__ import annotations

import json
from typing import Any

from arq.connections import ArqRedis

WORKER_KEY_PREFIX = "songmaker:acestep:worker"
QUEUE_KEY_PREFIX = "songmaker:acestep:queue"


def worker_state_key(worker_id: str) -> str:
    return f"{WORKER_KEY_PREFIX}:{worker_id}"


def queue_depth_key(worker_id: str) -> str:
    return f"{QUEUE_KEY_PREFIX}:{worker_id}"


async def read_worker_state(pool: ArqRedis, worker_id: str) -> dict[str, Any] | None:
    raw = await pool.get(worker_state_key(worker_id))
    if raw is None:
        return None
    return json.loads(raw)


async def read_queue_depth(pool: ArqRedis, worker_id: str) -> int:
    raw = await pool.get(queue_depth_key(worker_id))
    return int(raw) if raw is not None else 0


async def incr_queue_depth(pool: ArqRedis, worker_id: str) -> int:
    return await pool.incr(queue_depth_key(worker_id))


async def decr_queue_depth(pool: ArqRedis, worker_id: str) -> int:
    return await pool.decr(queue_depth_key(worker_id))


async def list_known_worker_states(pool: ArqRedis, worker_ids: list[str]) -> dict[str, dict[str, Any] | None]:
    return {wid: await read_worker_state(pool, wid) for wid in worker_ids}
```

Note: the key constants here **must match** the ones in `acestep_worker/heartbeat.py`. Same prefixes, same format. There's a risk of drift. Mitigation: a single test in `test_acestep_state.py` that imports both and asserts the prefixes match.

### D5. `internal_api.py` — router-level token dependency

```python
# src/songmaker_cli/internal_api.py
from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from songmaker_cli.api_models.workers import WorkerRegisterRequest, WorkerRegisterResponse
from songmaker_cli.app_context import get_db_session
from songmaker_cli.db.queries.workers import register_worker

log = logging.getLogger(__name__)

INTERNAL_TOKEN_ENV = "SONGMAKER_INTERNAL_TOKEN"


def verify_internal_token(x_internal_token: str = Header(..., alias="X-Internal-Token")) -> None:
    expected = os.environ.get(INTERNAL_TOKEN_ENV)
    if not expected:
        raise HTTPException(503, "Internal API not configured")
    if not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(401, "Invalid internal token")


router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(verify_internal_token)],
)


@router.post("/workers/register")
def register_worker_endpoint(
    req: WorkerRegisterRequest,
    db: Session = Depends(get_db_session),
) -> WorkerRegisterResponse:
    worker = register_worker(
        db,
        worker_id=req.worker_id,
        host=req.host,
        port=req.port,
        gpu_id=req.gpu_id,
        vram_total_gb=req.vram_total_gb,
    )
    db.commit()
    log.info("Worker registered: %s @ %s:%d", req.worker_id, req.host, req.port)
    return WorkerRegisterResponse(worker_id=worker.id, registered_at=worker.registered_at)
```

**Trust boundary:**
- Token check is at the router level so new endpoints inherit it automatically.
- `503` if the env var is unset (fail-closed: better than 401 because it tells the operator the issue is config, not credentials).
- `hmac.compare_digest` for timing safety.
- Mounted under `/api/internal/` (the `/api` prefix comes from `api.py:27`).

**Reverse proxy responsibility:** the operator must not expose `/api/internal/*` to the internet. Document this in `docs/security.md`.

### D6. Admin endpoints live in `admin_api.py` (extend existing file)

Keeping with the existing pattern. New section at the bottom of `admin_api.py`. The two existing acestep endpoints (`/acestep/status`, `/acestep/reinitialize`) **stay** in Phase 2 — they're deleted in Phase 3 cutover.

Endpoints to add:

```python
@router.get("/workers")
async def list_workers_endpoint(
    db: Session = Depends(get_db_session),
    pool: ArqRedis = Depends(get_arq_pool_dep),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> WorkerPoolResponse:
    ...


@router.get("/registry")
async def get_registry_endpoint(
    db: Session = Depends(get_db_session),
    pool: ArqRedis = Depends(get_arq_pool_dep),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> RegistryResponse:
    ...


@router.post("/workers/{worker_id}/load_model")
async def load_model_on_worker_endpoint(
    worker_id: str,
    req: LoadModelOnWorkerRequest,
    db: Session = Depends(get_db_session),
    pool: ArqRedis = Depends(get_arq_pool_dep),
    admin: AuthenticatedUser = Depends(require_admin),
) -> JobResponse:
    ...


@router.post("/workers/{worker_id}/evict_model")
async def evict_model_on_worker_endpoint(
    worker_id: str,
    req: EvictModelOnWorkerRequest,
    db: Session = Depends(get_db_session),
    pool: ArqRedis = Depends(get_arq_pool_dep),
    admin: AuthenticatedUser = Depends(require_admin),
) -> StatusResponse:
    ...
```

**Important distinctions:**
- `load_model` returns a `JobResponse` because the load takes 30-90s and the frontend will SSE-subscribe to the existing `/api/jobs/{id}/stream`.
- `evict_model` is synchronous (proxies directly to the worker, ~1s) and returns `StatusResponse`.
- Both endpoint impls **call the worker via httpx**, with the `X-Internal-Token` header.

### D7. Admin proxies use httpx, NOT a separate client class

Don't add an `acestep_worker_client.py`. The proxy logic is ~10 lines per endpoint. Inline it. If a third or fourth endpoint needs to call the worker, refactor then.

```python
async def _post_to_worker(host: str, port: int, path: str, json_body: dict | None = None) -> httpx.Response:
    token = os.environ.get(INTERNAL_TOKEN_ENV, "")
    headers = {"X-Internal-Token": token}
    async with httpx.AsyncClient(timeout=30) as client:
        return await client.post(f"http://{host}:{port}{path}", json=json_body, headers=headers)
```

This helper lives in `admin_api.py` (or pulled out to `acestep_state.py` if we want it shared with the scheduler later — punt that decision to Phase 3).

### D8. New `load_model_on_worker` arq job goes in `jobs.py`

The plan says "enqueues an arq job (`load_model_on_worker`) that proxies to the worker's `/load_model` and surfaces progress via the existing `/api/jobs/{job_id}/stream` SSE." This means:

1. Admin endpoint creates a `Job` row in PG
2. Endpoint enqueues the arq job with `_queue_name=ARQ_MUSIC_QUEUE_NAME`
3. The arq job handler:
   - `update_job_status(..., "running")`
   - calls `_post_to_worker(host, port, "/load_model", {"mode": req.mode})`
   - `update_job_status(..., "completed")` or `"failed"` based on response
4. Returns `JobResponse` to the admin frontend, which then SSE-subscribes to `/api/jobs/{job_id}/stream`

**Subtle point:** the arq job runs on the music-worker, which means the music-worker container needs to be able to reach the acestep-worker container over HTTP. Inside docker compose this is fine (worker DNS names resolve). After Phase 3 cutover the music-worker is the scheduler anyway, so this is consistent.

The job handler is a new function in `jobs.py`:

```python
async def load_model_on_worker(ctx, job_id: str, worker_id: str, mode: str) -> None:
    # 1. read worker host/port from PG
    # 2. update_job_status running
    # 3. POST to worker /load_model
    # 4. update_job_status completed/failed
    # 5. return result to job
    ...
```

**Defer to Phase 5:** the same pattern is reused for `download_model_on_worker`. Don't write that one yet.

### D9. SSE event forwarding is NOT in Phase 2

The plan mentions "forward SSE events from the worker's `/tasks/{task_id}/stream` to the existing `/api/jobs/{job_id}/stream`". This is a Phase 3 concern (the scheduler does the forwarding). For Phase 2, the admin's `load_model` endpoint:
1. Creates a job
2. The arq job calls the worker's `/load_model` (which is **synchronous** on the worker side and returns when load finishes)
3. The arq job marks complete on success / failed on error

The SSE stream just pushes job status changes from PG (which is what `/api/jobs/{id}/stream` already does for generation jobs). No new SSE plumbing in Phase 2.

This means a single `load_model` call from admin blocks the music-worker for ~30-90s. **Acceptable** for v1 because (a) the load is rare (admin action) and (b) the music-worker doesn't dispatch generations until Phase 3 anyway.

### D10. Frontend type generation happens at end of phase

`scripts/generate_types.py` runs once at the end of Phase 2 to regenerate `frontend/src/lib/api/types.ts`. The frontend changes themselves are Phase 4. Generating types in Phase 2 means Phase 4 starts with TypeScript types already in sync.

### D11. Tests use `make_test_app` + `arq_pool` fixture

Existing pattern: `make_test_app(tmp_path)` returns `(client, factory)`. Tests log in as admin via `_login_as_admin(client)`. The conftest already mocks the arq pool ([conftest.py:21-55](../tests/conftest.py#L21-L55)) — for the new tests, I'll need to extend it so the mocked pool returns realistic Redis state, **or** override the dependency directly with a `fakeredis.aioredis.FakeRedis` instance.

**Decision:** override the `get_arq_pool_dep` dependency in tests with a fresh `fakeredis.aioredis.FakeRedis`. Each test gets its own. Cleaner than fighting with the conftest mock, and matches what I did in Phase 1's wrapper tests.

```python
def _override_pool(client: TestClient, pool):
    from songmaker_cli.arq_pool import get_arq_pool_dep
    client.app.dependency_overrides[get_arq_pool_dep] = lambda: pool
```

## Files Touched (Phase 2)

| File | Change |
|---|---|
| `src/songmaker_cli/db/migrations/versions/<new>_acestep_workers.py` | New: alembic migration |
| `src/songmaker_cli/db/models.py` | Add `AceStepWorker` ORM model |
| `src/songmaker_cli/db/queries/workers.py` | New: `register_worker`, `list_worker_identities`, `get_worker_identity` |
| `src/songmaker_cli/db/queries/__init__.py` | Re-export new query functions |
| `src/songmaker_cli/acestep_state.py` | New: Redis key helpers + read functions |
| `src/songmaker_cli/api_models/workers.py` | New: `WorkerRegisterRequest`, `WorkerIdentity`, `WorkerEphemeralState`, `WorkerInfo`, `WorkerResponse`, `WorkerPoolResponse`, `RegistryModelResponse`, `RegistryResponse`, `LoadModelOnWorkerRequest`, `EvictModelOnWorkerRequest`, `WorkerRegisterResponse` |
| `src/songmaker_cli/api_models/__init__.py` | Re-export the new models |
| `src/songmaker_cli/internal_api.py` | New: `/api/internal/workers/register` with router-level token check |
| `src/songmaker_cli/api.py` | Mount `internal_router` |
| `src/songmaker_cli/admin_api.py` | Add `/admin/workers`, `/admin/registry`, `/admin/workers/{id}/load_model`, `/admin/workers/{id}/evict_model` |
| `src/songmaker_cli/arq_pool.py` | Add `get_arq_pool_dep` (one-line wrapper) |
| `src/songmaker_cli/jobs.py` | Add `load_model_on_worker` arq job handler |
| `src/songmaker_cli/music_worker.py` | Register `load_model_on_worker` in `WorkerSettings.functions` |
| `tests/test_internal_api.py` | New: token check passes/fails, registration upserts, missing token returns 401, missing env returns 503 |
| `tests/test_workers_queries.py` | New: identity CRUD, upsert behavior |
| `tests/test_acestep_state.py` | New: read_worker_state, read_queue_depth, incr/decr atomicity, key constant sync with `acestep_worker/heartbeat.py` |
| `tests/test_admin_api.py` | Add: list workers (joined PG+Redis), registry endpoint, load_model_on_worker enqueues + arq job runs, evict_model proxy |
| `tests/test_jobs.py` | Add: `load_model_on_worker` arq job handler — success, worker unreachable, worker returns 4xx |
| `docs/security.md` | New section: ACE-Step worker pool trust boundary |
| `frontend/src/lib/api/types.ts` | Regenerated by `scripts/generate_types.py` (no manual edits) |

## Implementation order (matches the order I'd execute)

1. **Read CLAUDE.md again** to refresh on conventions (1 min)
2. **`db/models.py`** add `AceStepWorker` (5 min)
3. **`db/migrations/`** new alembic revision (5 min — `alembic revision --autogenerate -m "add acestep_workers"` then verify the generated SQL)
4. **`db/queries/workers.py`** (10 min)
5. **`db/queries/__init__.py`** re-export (1 min)
6. **`tests/test_workers_queries.py`** (15 min) — verify CRUD before moving on
7. **`acestep_state.py`** (10 min)
8. **`tests/test_acestep_state.py`** (15 min) — including the prefix-sync test
9. **`api_models/workers.py`** (15 min — lots of small Pydantic classes, mostly mechanical)
10. **`api_models/__init__.py`** re-export (1 min)
11. **`arq_pool.py`** add `get_arq_pool_dep` (1 min)
12. **`internal_api.py`** new file (15 min)
13. **`api.py`** mount internal router (1 min)
14. **`tests/test_internal_api.py`** (20 min)
15. **`admin_api.py`** add the four new endpoints (30 min — the proxy logic is the trickiest part)
16. **`jobs.py`** add `load_model_on_worker` (15 min)
17. **`music_worker.py`** register the new job (5 min)
18. **`tests/test_admin_api.py`** add new test cases (40 min)
19. **`tests/test_jobs.py`** add new test cases (15 min)
20. **`docs/security.md`** new section (15 min)
21. **`scripts/generate_types.py`** run + commit the regenerated types (2 min)
22. **Self-review pass** — read every changed file via `git diff HEAD`, check for bugs (20 min)
23. **Run checks**: `ruff`, targeted pytest, full pytest, coverage 100% on new code (10 min)
24. **Commit + push** (5 min)

Total wall clock: ~4 hours of focused work. Don't try to compress this.

## Test strategy

### Critical test cases (write these first, they catch the most)

1. **Internal token check at router level** — make sure adding a new endpoint to `internal_router` automatically gets the token check. Test: monkey-patch the env var, hit a non-existent endpoint, assert it gets 401 (not 404). Catches the regression where someone adds `@app.post(...)` instead of `@router.post(...)`.

2. **`hmac.compare_digest` is actually used** — test with a token that's a prefix of the real token. A naive `==` would still reject it, but `compare_digest` is what guarantees timing safety. Hard to test directly; just verify in code review.

3. **Registration is idempotent (upsert)** — register the same worker_id twice with different host/port. Second call should update the row, not error. `last_register_at` should advance.

4. **Status derivation under all conditions:**
   - PG row exists, Redis key exists, target_loading=null → `online`
   - PG row exists, Redis key exists, target_loading="xl-sft" → `loading`
   - PG row exists, Redis key expired → `offline`
   - PG row missing → not in the list at all (worker was deleted or never registered)

5. **Registry endpoint computes `downloaded` as the union across workers** — set up two workers in Redis with different `available_modes`, verify the registry returns the union. Catches the bug where someone reads from one worker only.

6. **`/admin/workers/{id}/load_model` enqueues a job, then the arq job runs and proxies correctly** — this needs both an admin test (job created, JobResponse returned) AND a jobs test (the handler actually calls httpx, handles success/failure). The two halves are independent.

7. **`load_model_on_worker` job handles worker unreachable** — mock httpx to raise `httpx.ConnectError`, verify job status becomes `failed` with a clear error message. Tests the production failure mode where someone restarts the acestep-worker mid-load.

8. **Token-check returns 503 (not 401) when env var is unset** — separate "not configured" from "wrong credentials".

### Tests that would pass even if implementation is wrong (avoid these)

- ❌ Mocking `register_worker` and asserting it was called with the right args (tests the test, not the impl)
- ❌ Asserting status code 200 without checking the response body
- ❌ Using `assert response.json() != {}` (vacuous)
- ❌ Testing only the happy path for endpoints that have failure modes worth testing

### Coverage expectation

100% on all new files (`acestep_state.py`, `internal_api.py`, `db/queries/workers.py`, `api_models/workers.py`). The new code in `admin_api.py` and `jobs.py` should also hit 100% on the additions — existing code in those files keeps whatever coverage it had.

## Self-review checklist (run before commit)

1. **Re-read every changed file** in full via `git diff HEAD`. No skipping.
2. **`grep -n "TODO\|FIXME\|XXX"` on the diff** — flag anything left behind.
3. **No comments in new code** (per `feedback_code_standards.md`). Only `# noqa`, `# type: ignore`, `# pragma: no cover` are allowed.
4. **No hardcoded magic strings** — all key prefixes, env var names, table names go through constants.
5. **Every endpoint has `Depends(require_admin)` or `Depends(verify_internal_token)`**. Grep the new endpoints for this.
6. **Every PG-mutating endpoint has `db.commit()`** before returning. Grep for `register_worker(` and verify a commit follows.
7. **The flush/commit pattern**: `db/queries/workers.py:register_worker` calls `session.flush()`, the endpoint calls `session.commit()`.
8. **`from_orm()` classmethods on response models**, never hand-built dicts.
9. **Engine isolation**: `acestep_engine` and `acestep_worker` must not import from `songmaker_cli` (verify with `grep -r "from songmaker_cli" src/acestep_engine src/acestep_worker`). The other direction is fine.
10. **`scripts/generate_types.py`** ran at the end and produced a valid TypeScript file with no diff issues.
11. **Full project test suite passes** (not just the new tests). Run `pytest tests/ --ignore=tests/test_scorers.py --ignore=tests/test_scorers_extended.py -q` and verify 1000+ pass, 0 fail.

## Things to watch out for

### Watchpoint 1: Redis key drift between `acestep_worker/heartbeat.py` and `songmaker_cli/acestep_state.py`

These two modules write/read the **same** Redis keys but live in different packages and don't share a constants source. **Mitigation:** add a test in `test_acestep_state.py` that imports `acestep_worker.heartbeat.WORKER_KEY_PREFIX` and `songmaker_cli.acestep_state.WORKER_KEY_PREFIX` and asserts they match.

This is a "real bug if they diverge" test, not a vacuous test.

### Watchpoint 2: `register_worker` upsert semantics

There are two reasonable definitions of "register":
- **A: Insert or fail** — second registration with same ID raises `IntegrityError`
- **B: Upsert** — second registration updates host/port/etc and bumps `last_register_at`

The plan says "idempotent (upserts by `worker_id`)". Use B. The implementation:

```python
def register_worker(
    session: Session,
    *,
    worker_id: str,
    host: str,
    port: int,
    gpu_id: int | None,
    vram_total_gb: float | None,
) -> AceStepWorker:
    existing = session.get(AceStepWorker, worker_id)
    if existing is not None:
        existing.host = host
        existing.port = port
        existing.gpu_id = gpu_id
        existing.vram_total_gb = vram_total_gb
        existing.last_register_at = _utcnow()
        session.flush()
        return existing
    worker = AceStepWorker(
        id=worker_id,
        host=host,
        port=port,
        gpu_id=gpu_id,
        vram_total_gb=vram_total_gb,
    )
    session.add(worker)
    session.flush()
    return worker
```

Don't use `INSERT ... ON CONFLICT` — it's PostgreSQL-specific and the test DB is SQLite. This get-then-update-or-insert pattern works on both.

### Watchpoint 3: Env var ordering for `SONGMAKER_INTERNAL_TOKEN`

`internal_api.py` reads `SONGMAKER_INTERNAL_TOKEN` at request time (inside `verify_internal_token`). This is **correct** — it means tests can monkey-patch the env var per-test. Don't refactor it to module-level constant resolution; that would break test isolation.

### Watchpoint 4: The arq pool fixture mock

[conftest.py:21-55](../tests/conftest.py#L21-L55) mocks `init_arq_pool` to return an `AsyncMock` with a fixed set of methods (`zcard`, `keys`, `get`, `aclose`). The new tests need `set`, `incr`, `decr`, `delete`, `exists` too. **Either:**
- (A) Extend the conftest mock — risk: bleeds into other tests
- (B) Override `get_arq_pool_dep` per-test with a real `fakeredis.aioredis.FakeRedis` — preferred

Use B. Each new test creates its own `fakeredis.aioredis.FakeRedis` instance and overrides the dependency. Don't touch the existing conftest mock.

### Watchpoint 5: alembic migration must handle the existing DB state

The existing prod DB doesn't have an `acestep_workers` table. The migration creates it. There's no data migration needed (table is new), so the migration is just `op.create_table(...)`. Verify the autogenerate works:

```bash
alembic revision --autogenerate -m "add acestep_workers"
```

And **manually inspect** the generated file before committing. Autogenerate sometimes adds spurious operations (e.g., re-creating indexes). Strip anything that isn't the new table.

### Watchpoint 6: `music_worker.py` `WorkerSettings.functions` registration

The `load_model_on_worker` arq job needs to be added to the music-worker's function list. Find `WorkerSettings` in `music_worker.py`, locate the `functions` tuple/list, and add the new job. **Don't forget this step** — without it, the arq pool can enqueue the job but no worker will pick it up.

### Watchpoint 7: docs/security.md trust boundary section

Don't write a 500-line essay. The section should cover:
- What `SONGMAKER_INTERNAL_TOKEN` is
- Where it's used (internal_api endpoints, scheduler→worker calls)
- How to rotate it (set new env var, restart all containers, no DB state to update)
- What a compromised worker can reach (PG via existing creds; Redis; the volume mount it has; **cannot** reach auth tables — workers only call `/api/internal/workers/register`)
- The reverse proxy rule: `/api/internal/*` must not be exposed to the internet (give an explicit nginx `location` example)
- Future hardening note: "binding internal endpoints to a separate port is the next step if internet exposure becomes a risk"

About 60-80 lines total.

## What is NOT in Phase 2 (deferred to later phases)

- **Scheduler** — Phase 3 (lives in music-worker)
- **`docs/architecture.md`** — Phase 3 (cutover phase, where the architecture actually changes)
- **Frontend Worker Pool / Model Registry panels** — Phase 4
- **`download_model_on_worker` arq job** — Phase 5
- **Worker metrics in `/metrics`** — Phase 6
- **Restart endpoint** — Phase 6
- **Concurrent in-flight handling for load while generating** — Phase 6

If you find yourself implementing any of these in Phase 2, **stop**. They're not in scope.

## Branching

Phase 2 commits go on `feat/acestep-worker-pool` (the same branch as Phase 1). One commit per atomic chunk is fine, or one big commit at the end — the user's preference is "fewer intermediate test runs, more parallelism" per `feedback_speed.md`. I'd suggest 2-3 commits:

1. PG layer: model + migration + queries + tests
2. Redis layer + internal_api + admin endpoints + tests
3. Job handler + music_worker registration + docs + type regen

Or one big commit if the chunks aren't independently meaningful.

Push to `origin/feat/acestep-worker-pool` after each commit.

## Quick context for next session's first message

If you're a new agent picking this up: read `CLAUDE.md`, read [acestep-worker-pool.md](acestep-worker-pool.md), then read this file. Phase 1 is committed and pushed. The branch is `feat/acestep-worker-pool`. Run `git log --oneline -5` to see the current state. Phase 1's `acestep_worker/` package is at `src/acestep_worker/` and its tests at `tests/acestep_worker/` — read those briefly to see the conventions I followed (no comments, dataclass deps, pydantic models, sync test functions calling `asyncio.run`, fakeredis for redis tests).

When you're done with exploration, start at step 1 of "Implementation order" above.
