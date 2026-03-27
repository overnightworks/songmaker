# Migration: In-Process GPU Queue → arq

> **Status: NOT STARTED** — depends on Redis migration (Redis serves as arq's backend).
> **Depends on: Phase 0 + Redis migration**

## Problem

The GPU queue is an in-process `queue.Queue` with a single worker thread. Jobs are lost on restart (only running/stale jobs are recovered, queued items vanish). The queue can't span multiple machines or GPUs. Thread-based timeouts can't kill stuck jobs — zombie threads consume resources indefinitely. If the worker thread dies from an unhandled exception, subsequent jobs queue forever silently (`gpu_queue.py:130-135`).

## Goal

Replace the in-process queue with arq workers, using Redis as the job backend. Jobs become durable, observable, and distributable. The worker process runs separately from the API server, with process-level timeout enforcement.

## Why arq over Celery

- **Async-native**: arq is asyncio-based, fits FastAPI naturally. Celery is sync-only.
- **One process**: worker + cron in a single process. Celery needs worker + beat (2 processes).
- **Built-in health checks**: arq writes a health key to Redis automatically. Celery needs `control.ping()` which is slow.
- **Built-in cron**: `cron()` function replaces Celery Beat entirely.
- **JSON-only**: no pickle serialization (no deserialization attacks). Celery defaults to pickle.
- **Simple timeouts**: `job_timeout` sends SIGTERM. Celery has `soft_time_limit` AND `time_limit` with different signals.
- **Tiny dependency**: ~1000 lines. Celery is ~50,000 lines with kombu, vine, billiard, etc.
- **Job deduplication**: built-in by job ID. Celery needs `celery-once` or manual locking.

If we outgrow arq (10+ task types, complex routing, RabbitMQ), swapping to Celery is ~half a day — the job functions, DB queries, and ACE-Step manager are all unchanged.

## Architecture

```
Current:
  FastAPI (thread: gpu-queue-worker)
    └→ Queue() → _execute() → job.fn()

Target:
  FastAPI (API only, no GPU work)
    └→ await arq_pool.enqueue_job("generate", ...)

  arq Worker (separate process, GPU access)
    ├→ generate function
    ├→ score function
    ├→ cleanup_stale_jobs (cron, every 15 min)
    └→ ACE-Step lifecycle (startup/shutdown hooks)
```

## Complete Caller Inventory

Every location that touches `GpuQueue` must be migrated. File:line references are exact.

### GpuQueue creation and lifecycle

| Location | What it does | Migration |
|----------|-------------|-----------|
| `server.py:417-419` | `GpuQueue(db_factory)` creation | Skip when arq worker is configured (Redis agent wired this) |
| `server.py:439-440` | `gpu_q.start()` | Skip when arq worker is configured (Redis agent wired this) |
| `server.py:391-393` | `gpu_q.shutdown()` in lifespan | Skip when `gpu_queue is None` (Phase 0 already does this) |
| `app_context.py:27` | `gpu_queue: GpuQueue \| None` | Keep None when using arq |

### Job submission (callers of `gpu_queue.submit()`)

| Location | Job type | Current call | arq replacement |
|----------|----------|-------------|-----------------|
| `generation_api.py:101` | `"generate"` | `ctx.gpu_queue.submit(job.id, "generate", run_generation_job, args=(...))` | `await arq_pool.enqueue_job("generate", job.id, song_id, version_id, count, model)` |
| `generation_api.py:124` | `"score"` | `ctx.gpu_queue.submit(job.id, "score", run_scoring_job, args=(...))` | `await arq_pool.enqueue_job("score", job.id, gen_id, scorers)` |

**No other callers exist.** Verified by searching for `gpu_queue.submit`, `_queue.put`, and all `GpuQueue` references.

### GpuQueue property reads

| Location | Property | arq replacement |
|----------|----------|-----------------|
| `server.py` metrics | `gpu_q.queue_depth` | `redis.zcard(arq_queue_name)` (arq uses sorted set) |
| `server.py` health | `gpu_q.is_running` | `redis.exists(worker_health_check_key)` (arq built-in) |
| `server.py` health | `gpu_q.acestep_healthy` | HTTP health check to ACE-Step (unchanged) |
| `server.py` metrics | `gpu_q.active_model` | Redis key `songmaker:active_model` set by worker |
| `admin_api.py:155-176` | `ctx.gpu_queue` (reinitialize/status) | Admin endpoints query Redis keys + ACE-Step HTTP |

### Internal GpuQueue methods that become arq worker internals

| Method | Line | arq equivalent |
|--------|------|----------------|
| `_run()` | 130-135 | arq worker main loop (built-in) |
| `_execute()` | 137-170 | arq task execution (built-in `job_timeout`) |
| `_prepare_mode()` | 188-207 | Called at start of each task function |
| `_clear_scoring_models()` | 210-229 | Called at start of each task function |
| `_verify_vram_freed()` | 210 | Called at start of each task function |
| `_ensure_acestep()` | 233-240 | `on_startup` hook |
| `_start_acestep()` | 250-273 | `on_startup` hook |
| `_stop_acestep()` | 289-306 | `on_shutdown` hook |
| `_recover_stale_jobs()` | 80-96 | `on_startup` hook (same DB query) |
| `_periodic_cleanup()` | 98-109 | `cron()` function (built-in, no extra process) |

## Steps

### Phase 1: arq setup

- [ ] Add `arq>=0.26` to `pyproject.toml` server extras
- [ ] Create `src/songmaker_cli/arq_pool.py` — connection pool for the API side:
  ```python
  from arq import create_pool
  from arq.connections import RedisSettings

  _pool = None

  async def get_arq_pool():
      global _pool
      if _pool is None:
          _pool = await create_pool(
              RedisSettings.from_dsn(os.environ["REDIS_URL"])
          )
      return _pool

  async def close_arq_pool():
      global _pool
      if _pool:
          await _pool.close()
          _pool = None
  ```

- [ ] Wire pool lifecycle into `server.py` lifespan:
  ```python
  @asynccontextmanager
  async def _lifespan(app: FastAPI):
      # ... existing startup ...
      if app.state.ctx.redis:
          from songmaker_cli.arq_pool import get_arq_pool
          app.state.arq_pool = await get_arq_pool()
      yield
      if app.state.ctx.redis:
          from songmaker_cli.arq_pool import close_arq_pool
          await close_arq_pool()
      # ... existing shutdown ...
  ```

### Phase 2: Worker definition

- [ ] Create `src/songmaker_cli/worker.py`:
  ```python
  import os
  from pathlib import Path
  from arq import cron
  from arq.connections import RedisSettings

  from songmaker_cli.db.engine import init_db, resolve_database_url
  from songmaker_cli.db.queries import get_job, recover_stale_jobs, recover_stale_jobs_by_age
  from songmaker_cli.jobs import run_generation_job, run_scoring_job

  _db_factory = None
  _acestep_manager = None
  _current_mode = None

  def _get_db_factory():
      global _db_factory
      if _db_factory is None:
          output_dir = Path(os.environ.get("OUTPUT_DIR", "_output"))
          _db_factory = init_db(resolve_database_url(output_dir))
      return _db_factory

  def _output_dir():
      return Path(os.environ.get("OUTPUT_DIR", "_output"))


  async def generate(ctx, job_id, song_id, version_id, count, model):
      db_factory = _get_db_factory()

      # Idempotency: skip if already in terminal status
      with db_factory() as session:
          job = get_job(session, job_id)
          if not job or job.status in ("completed", "partial", "failed"):
              return

      # Mode switching: ensure ACE-Step is running, clear scoring models if needed
      global _current_mode
      if _current_mode != "generate":
          _prepare_generate_mode()
          _current_mode = "generate"

      import structlog
      structlog.contextvars.bind_contextvars(job_id=job_id, task="generate")

      run_generation_job(db_factory, _output_dir(), job_id, song_id, version_id, count, model)


  async def score(ctx, job_id, gen_id, scorers):
      db_factory = _get_db_factory()

      with db_factory() as session:
          job = get_job(session, job_id)
          if not job or job.status in ("completed", "partial", "failed"):
              return

      global _current_mode
      if _current_mode != "score":
          _prepare_score_mode()
          _current_mode = "score"

      import structlog
      structlog.contextvars.bind_contextvars(job_id=job_id, task="score")

      run_scoring_job(db_factory, _output_dir(), job_id, gen_id, scorers)


  async def cleanup_stale(ctx):
      db_factory = _get_db_factory()
      with db_factory() as session:
          count = recover_stale_jobs_by_age(session)
          if count:
              session.commit()


  async def on_startup(ctx):
      global _acestep_manager
      from songmaker_cli.acestep_manager import AceStepManager
      _acestep_manager = AceStepManager()
      _acestep_manager.start()
      _acestep_manager.wait_for_health()

      # Recover any jobs that were running when the worker last died
      db_factory = _get_db_factory()
      with db_factory() as session:
          recover_stale_jobs(session)
          session.commit()


  async def on_shutdown(ctx):
      if _acestep_manager:
          _acestep_manager.stop()


  class WorkerSettings:
      functions = [generate, score]
      on_startup = on_startup
      on_shutdown = on_shutdown
      redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
      max_jobs = 1                # GPU serialization — one job at a time
      job_timeout = 300           # SIGTERM after 5 min
      health_check_interval = 30  # write health key every 30s
      cron_jobs = [
          cron(cleanup_stale, hour=None, minute={0, 15, 30, 45}),
      ]
  ```

- [ ] **Idempotency contract**: A task that finds its job already in a terminal status (`completed`, `partial`, `failed`) returns immediately without side effects. This handles:
  - arq retry after worker crash
  - Duplicate job enqueue (network retry)
  - Partial completion: if generation loop created some files but worker died, the job stays `running`. On retry, the idempotency check sees `running` (not terminal) and re-executes. `run_generation_job` creates new generation records — duplicates are possible but harmless (user deletes extras).

- [ ] **structlog context**: arq workers are separate processes — `structlog.contextvars` don't cross process boundaries. Each task binds its own context vars at the start.

### Phase 3: Extract AceStepManager

- [ ] Create `src/songmaker_cli/acestep_manager.py` — extract from `GpuQueue`:
  - `start()` — from `_start_acestep()` (line 250-273)
  - `stop()` — from `_stop_acestep()` (line 289-306)
  - `is_healthy()` — from `_is_acestep_healthy()` (line 242-248)
  - `wait_for_health()` — from `_wait_for_acestep()` (line 276-287)
  - `_prepare_generate_mode()` — from `_prepare_mode("generate")` (line 188-207)
  - `_prepare_score_mode()` — clear scoring models + verify VRAM freed (line 210-229)

- [ ] **Environment variables**: ACE-Step subprocess currently inherits `os.environ.copy()` (`gpu_queue.py:257`). In arq worker, only pass needed vars: `ACESTEP_API_PORT`, `ACESTEP_DEVICE`, `ACESTEP_CONFIG_PATH`, `CUDA_VISIBLE_DEVICES`. Do NOT pass `ANTHROPIC_API_KEY` or `SESSION_SECRET`.

- [ ] **Multiple workers on multiple GPUs**: Each arq worker starts its own ACE-Step instance. Pin each worker to a specific GPU via `CUDA_VISIBLE_DEVICES`. arq doesn't have worker IDs, but each process gets its own module-level `_acestep_manager`.

### Phase 4: Replace GpuQueue submission in API

- [ ] `generation_api.py:101`: Replace `ctx.gpu_queue.submit(...)` with:
  ```python
  if ctx.redis:  # arq uses Redis as backend
      pool = request.app.state.arq_pool
      await pool.enqueue_job("generate", job.id, song_id, version.id, req.count, req.model)
  else:
      ctx.gpu_queue.submit(job.id, "generate", run_generation_job, args=(...))
  ```

- [ ] `generation_api.py:124`: Same pattern for scoring

- [ ] **Important**: `enqueue_job` is async — the endpoint functions that call it must be `async def`, not `def`. Currently they're sync (`def api_generate_song`). Either:
  - Convert to `async def` (preferred — FastAPI handles this natively)
  - Or use `asyncio.run()` / `loop.run_until_complete()` (ugly, avoid)

- [ ] If Redis is down, `enqueue_job` raises `ConnectionError` — catch and return `HTTPException(503, "Job queue unavailable")`

- [ ] Keep `Job` record creation in the API (before enqueue) — same as now.

### Phase 5: Observability

- [ ] **Queue depth**: arq uses a sorted set `arq:queue` — `redis.zcard("arq:queue")` returns pending job count. Expose via `/metrics`.

- [ ] **Worker health**: arq automatically writes `arq:worker:{worker_name}` key with TTL. Check `redis.exists("arq:worker:*")` for worker alive status. Expose via `/health`.

- [ ] **Active model**: Worker sets `redis.set("songmaker:active_model", model_name)` when switching modes. API reads this for `/metrics` and `/health`.

- [ ] **Task duration**: Log start/end times with structlog in each task function. arq also stores `start_time` and `finish_time` on the job result in Redis.

### Phase 6: Remove in-process queue

- [ ] Delete `gpu_queue.py` (entire file)
- [ ] Remove `GpuQueue` from `app_context.py`
- [ ] Remove `GpuQueue` import guard in `server.py`
- [ ] Remove in-process `GpuQueue` fallback — arq becomes the only path
- [ ] Update `docs/architecture.md`

## Design Decisions

### Worker concurrency
`max_jobs=1` — same as current single-threaded queue. GPU work must be serialized. Multiple GPUs = multiple arq workers, each pinned to a GPU via `CUDA_VISIBLE_DEVICES`.

### Task serialization
arq uses JSON only (msgpack optional). Task args are primitives (strings, ints, lists). No pickle, no deserialization attacks. The task function creates its own DB session from `DATABASE_URL`.

### Timeout enforcement
arq's `job_timeout` sends SIGTERM to the task coroutine. If the task doesn't exit within a grace period, the worker process restarts. For GPU jobs that can truly hang (CUDA deadlock), the Docker `--stop-timeout` serves as the SIGKILL backstop. This is a meaningful improvement over the current `thread.join(timeout)` which can't kill stuck threads at all.

### Async task functions calling sync job runners
`run_generation_job` and `run_scoring_job` are sync functions (CPU/GPU-bound). arq runs async tasks, but since `max_jobs=1`, there's no concurrency concern — the sync function blocks the single worker slot. For cleanliness, wrap in `asyncio.to_thread()` if needed, but with `max_jobs=1` it doesn't matter.

### Job idempotency
If the worker dies, arq can retry the job (configurable). The task checks if the Job record is already in a terminal status. If so, it returns immediately. Edge case: worker dies after creating generation records but before marking job complete — retry creates duplicate generations. Acceptable (user deletes extras) and preferable to lost work.

### Structlog across processes
arq workers are separate processes. `structlog.contextvars` bindings from the API process don't carry over. Each task binds its own context vars at the start of execution.

### Backwards compatibility
- Feature flag: `REDIS_URL` env var — when set, arq is available
- When unset: fall back to in-process `GpuQueue` (current behavior)
- Phase 6 removes the flag and the old code path

## Docker Compose

```yaml
services:
  redis:
    image: redis:7-alpine
    volumes: [redis-data:/data]

  api:
    build: .
    command: songmaker server --port 8080
    environment:
      REDIS_URL: redis://redis:6379/0
      DATABASE_URL: postgresql://...
      # arq uses REDIS_URL — no separate flag needed

  worker:
    build: .
    command: arq songmaker_cli.worker.WorkerSettings
    environment:
      REDIS_URL: redis://redis:6379/0
      DATABASE_URL: postgresql://...
      ACESTEP_DEVICE: cuda:0
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
```

No Beat process needed — cron is built into the worker.

## Testing

- Unit tests: mock `arq_pool.enqueue_job()`, verify correct args passed
- Integration test: real arq worker + Redis in Docker, submit job, poll until complete
- Timeout test: submit task that sleeps forever, verify worker recovers after `job_timeout`
- Idempotency test: manually set job to "completed", enqueue task, verify no-op
- Health check test: start worker, verify health key exists in Redis; stop worker, verify key expires
- Cron test: verify `cleanup_stale` runs on schedule and marks stale jobs as failed
- Existing test suite: runs unchanged (tests call `run_generation_job()` directly, not via queue)
- structlog test: verify task logs include `job_id` context

## Files Owned

For coordination with parallel agents:
- `worker.py` (new)
- `arq_pool.py` (new)
- `acestep_manager.py` (new)
- `generation_api.py:96-130` (submission calls)
- `server.py:376-440` (lifespan, arq pool lifecycle)
- `gpu_queue.py` (deleted in Phase 6)
