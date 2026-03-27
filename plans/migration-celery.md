# Migration: In-Process GPU Queue → Celery

> **Status: NOT STARTED** — depends on Redis migration (Redis serves as Celery broker).
> **Depends on: Phase 0 + Redis migration**

## Problem

The GPU queue is an in-process `queue.Queue` with a single worker thread. Jobs are lost on restart (only running/stale jobs are recovered, queued items vanish). The queue can't span multiple machines or GPUs. Thread-based timeouts can't kill stuck jobs — zombie threads consume resources indefinitely. If the worker thread dies from an unhandled exception, subsequent jobs queue forever silently (`gpu_queue.py:130-135`).

## Goal

Replace the in-process queue with Celery workers, using Redis as the message broker. Jobs become durable, observable, and distributable. The worker process runs separately from the API server, with proper process-level timeout enforcement.

## Architecture

```
Current:
  FastAPI (thread: gpu-queue-worker)
    └→ Queue() → _execute() → job.fn()

Target:
  FastAPI (API only, no GPU work)
    └→ celery.send_task("generate", args)

  Celery Worker (separate process, GPU access)
    ├→ generate task
    ├→ score task
    └→ ACE-Step lifecycle management
```

## Complete Caller Inventory

Every location that touches `GpuQueue` must be migrated. File:line references are exact.

### GpuQueue creation and lifecycle

| Location | What it does | Migration |
|----------|-------------|-----------|
| `server.py:414` | `gpu_q = GpuQueue(db_factory)` | Skip when `USE_CELERY` set |
| `server.py:425` | `gpu_q.start()` | Skip when `USE_CELERY` set |
| `server.py:391-393` | `gpu_q.shutdown()` in lifespan | Skip when `USE_CELERY` set |
| `app_context.py:25` | `gpu_queue: GpuQueue \| None` | Keep None when using Celery |

### Job submission (callers of `gpu_queue.submit()`)

| Location | Job type | Current call | Celery replacement |
|----------|----------|-------------|-------------------|
| `generation_api.py:101` | `"generate"` | `ctx.gpu_queue.submit(job.id, "generate", run_generation_job, args=(...))` | `generate_task.delay(job.id, song_id, version_id, count, model)` |
| `generation_api.py:124` | `"score"` | `ctx.gpu_queue.submit(job.id, "score", run_scoring_job, args=(...))` | `score_task.delay(job.id, gen_id, scorers)` |

**No other callers exist.** Verified by searching for `gpu_queue.submit`, `_queue.put`, and all `GpuQueue` references.

### GpuQueue property reads

| Location | Property | Migration |
|----------|----------|-----------|
| `server.py:498-502` | `gpu_q.queue_depth` | Redis `LLEN` on Celery broker queue |
| `server.py:503-506` | `gpu_q.is_running` | `celery.control.ping()` |
| `server.py:507-509` | `gpu_q.acestep_healthy` | HTTP health check from API (same as now) |
| `server.py:510-512` | `gpu_q.active_model` | Redis key set by worker on model switch |
| `admin_api.py:155-176` | `ctx.gpu_queue` (reinitialize/status) | Celery worker restart signal or admin API on worker |

### Internal GpuQueue methods that become Celery worker internals

| Method | Line | Celery equivalent |
|--------|------|-------------------|
| `_run()` | 130-135 | Celery worker main loop (built-in) |
| `_execute()` | 137-170 | Celery task execution (built-in timeout via `time_limit`) |
| `_prepare_mode()` | 188-207 | Pre-task signal or task preamble |
| `_clear_scoring_models()` | 210-229 | Same, called in task preamble |
| `_verify_vram_freed()` | 210 | Same |
| `_ensure_acestep()` | 233-240 | Worker startup hook |
| `_start_acestep()` | 250-273 | Worker startup hook |
| `_stop_acestep()` | 289-306 | Worker shutdown hook |
| `_recover_stale_jobs()` | 80-96 | Celery `acks_late=True` handles this |
| `_periodic_cleanup()` | 98-109 | Celery Beat scheduled task |

## Steps

### Phase 1: Celery setup

- [ ] Add `celery[redis]>=5.3` to `pyproject.toml` server extras
- [ ] Create `src/songmaker_cli/celery_app.py`:
  ```python
  from celery import Celery

  app = Celery("songmaker")
  app.config_from_object({
      "broker_url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
      "result_backend": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
      "worker_concurrency": 1,          # GPU serialization
      "task_acks_late": True,            # redelivers if worker dies
      "task_reject_on_worker_lost": True,# requeue on worker crash
      "task_time_limit": 360,            # SIGKILL after 6 min
      "task_soft_time_limit": 300,       # SoftTimeLimitExceeded after 5 min
      "task_serializer": "json",         # no pickle
      "accept_content": ["json"],
      "worker_hijack_root_logger": False,# keep structlog
  })
  ```

### Phase 2: Task definitions

- [ ] Create `src/songmaker_cli/tasks.py`:
  ```python
  from songmaker_cli.celery_app import app
  from songmaker_cli.db.engine import init_db

  def _get_db_factory():
      url = os.environ["DATABASE_URL"]
      return init_db(url)

  @app.task(name="generate", bind=True)
  def generate_task(self, job_id, song_id, version_id, count, model):
      # Idempotency check (critical for acks_late redelivery)
      db_factory = _get_db_factory()
      with db_factory() as session:
          job = get_job(session, job_id)
          if not job or job.status in ("completed", "partial", "failed"):
              return  # already processed — skip

      run_generation_job(db_factory, Path(os.environ.get("OUTPUT_DIR", "_output")),
                         job_id, song_id, version_id, count, model)

  @app.task(name="score", bind=True)
  def score_task(self, job_id, gen_id, scorers):
      # Idempotency check
      db_factory = _get_db_factory()
      with db_factory() as session:
          job = get_job(session, job_id)
          if not job or job.status in ("completed", "partial", "failed"):
              return

      run_scoring_job(db_factory, Path(os.environ.get("OUTPUT_DIR", "_output")),
                      job_id, gen_id, scorers)

  @app.task(name="cleanup_stale_jobs")
  def cleanup_stale_jobs_task():
      db_factory = _get_db_factory()
      with db_factory() as session:
          count = recover_stale_jobs_by_age(session)
          if count:
              session.commit()
  ```

- [ ] **Idempotency contract**: A task that finds its job already in a terminal status (`completed`, `partial`, `failed`) returns immediately without side effects. This handles:
  - Celery redelivery after worker crash (`acks_late=True`)
  - Duplicate task submission (network retry)
  - Partial completion: if generation loop created some files but worker died, the job stays `running`. On redelivery, the idempotency check sees `running` (not terminal) and re-executes. The `run_generation_job` function creates new generation records — duplicates are possible but harmless (user sees extra generations, can delete).

- [ ] **structlog context**: Celery tasks run in a separate process — `structlog.contextvars` don't cross process boundaries. Each task must call `structlog.contextvars.bind_contextvars(job_id=job_id, user_id=user_id)` at the start. Add this to both task functions.

### Phase 3: Replace GpuQueue submission

- [ ] `generation_api.py:101`: Replace `ctx.gpu_queue.submit(...)` with:
  ```python
  if ctx.use_celery:
      generate_task.delay(job.id, song_id, version.id, req.count, req.model)
  else:
      ctx.gpu_queue.submit(job.id, "generate", run_generation_job, args=(...))
  ```

- [ ] `generation_api.py:124`: Same pattern for scoring

- [ ] If Celery/Redis is down, `delay()` raises `kombu.exceptions.OperationalError` — catch and return `HTTPException(503, "Job queue unavailable")`

- [ ] Keep `Job` record creation in the API (before task submission) — same as now. The Job row acts as the durable record; Celery is just the execution mechanism.

### Phase 4: ACE-Step lifecycle in worker

- [ ] Move ACE-Step management to Celery worker signals:
  ```python
  from celery.signals import worker_init, worker_shutdown

  _acestep_manager = None  # module-level, per-worker process

  @worker_init.connect
  def on_worker_init(**kwargs):
      global _acestep_manager
      _acestep_manager = AceStepManager()  # extract from GpuQueue
      _acestep_manager.start()
      _acestep_manager.wait_for_health()

  @worker_shutdown.connect
  def on_worker_shutdown(**kwargs):
      if _acestep_manager:
          _acestep_manager.stop()
  ```

- [ ] Extract ACE-Step lifecycle methods from `GpuQueue` into standalone `AceStepManager` class:
  - `start()` — from `_start_acestep()` (line 250-273)
  - `stop()` — from `_stop_acestep()` (line 289-306)
  - `is_healthy()` — from `_is_acestep_healthy()` (line 242-248)
  - `wait_for_health()` — from `_wait_for_acestep()` (line 276-287)

- [ ] **Multiple workers on multiple GPUs**: Each worker process starts its own ACE-Step instance. Use `CUDA_VISIBLE_DEVICES` env var to pin each worker to a specific GPU. ACE-Step already reads `ACESTEP_DEVICE` from env (`gpu_queue.py:260`).

- [ ] VRAM management between task types:
  - Before generate task: call `_clear_scoring_models()` logic if previous task was scoring
  - Before score task: no ACE-Step needed, but verify VRAM freed
  - Track `_current_mode` as module-level state in worker process (same as current `gpu_queue.py:61`)
  - Use Celery `task_prerun` signal to handle mode switching

- [ ] **Environment variables**: ACE-Step subprocess currently inherits `os.environ.copy()` (`gpu_queue.py:257`). In Celery worker, only pass needed vars: `ACESTEP_API_PORT`, `ACESTEP_DEVICE`, `ACESTEP_CONFIG_PATH`, `CUDA_VISIBLE_DEVICES`. Do NOT pass `ANTHROPIC_API_KEY` or `SESSION_SECRET`.

### Phase 5: Observability

- [ ] Queue depth: `redis.llen("celery")` (default Celery queue name), expose via `/metrics`
- [ ] Active task: `celery.control.inspect().active()`, expose via `/health`
- [ ] Worker alive: `celery.control.ping()`, expose via `/health`
- [ ] Task duration: Celery `task_prerun` / `task_postrun` signals log timing with structlog
- [ ] Set `active_model` in Redis key when worker switches model (for `/metrics` display)
- [ ] Flower (optional): web UI for Celery monitoring

### Phase 6: Celery Beat for periodic tasks

- [ ] Replace `_periodic_cleanup()` daemon thread (`gpu_queue.py:98-109`) with Beat schedule:
  ```python
  app.conf.beat_schedule = {
      "cleanup-stale-jobs": {
          "task": "cleanup_stale_jobs",
          "schedule": CLEANUP_INTERVAL_SECONDS,  # from constants, default 900
      },
  }
  ```
- [ ] The cleanup task calls `recover_stale_jobs_by_age()` (`db/queries/jobs.py:103-125`) — uses `STALE_JOB_THRESHOLD_SECONDS` env var (default 1800s)

### Phase 7: Remove in-process queue

- [ ] Delete `gpu_queue.py` (entire file)
- [ ] Remove `GpuQueue` from `app_context.py` (line 25)
- [ ] Remove GPU queue creation and startup from `server.py` (lines 414, 425, 391-393)
- [ ] Remove `UVICORN_WORKERS > 1` guard (`server.py:742-747`) — now safe
- [ ] Remove `USE_CELERY` feature flag — Celery becomes the only path
- [ ] Update `docs/architecture.md`

## Design Decisions

### Worker concurrency
`worker_concurrency=1` — same as current single-threaded queue. GPU work must be serialized. Multiple GPUs = multiple workers with `--concurrency=1` each, each pinned to a GPU via `CUDA_VISIBLE_DEVICES`.

### Task serialization
JSON serializer (not pickle). Task args are primitives (strings, ints, lists). No need to serialize complex objects. The task function creates its own DB session from `DATABASE_URL`.

### Timeout enforcement
Celery's `time_limit` sends SIGKILL to the worker process after the hard limit. This **actually kills** stuck jobs, unlike the current `thread.join(timeout)` approach (`gpu_queue.py:160-162`). This is the single biggest improvement of this migration.

### Job idempotency
`acks_late=True` means if the worker dies, the message goes back to the queue. On redelivery, the task checks if the Job record is already in a terminal status. If so, it skips execution. This handles crash recovery without creating duplicate outputs in the common case. Edge case: worker dies after creating generation records but before marking job complete — redelivery creates duplicate generations. This is acceptable (user can delete extras) and preferable to lost work.

### Structlog across processes
Celery workers are separate processes. `structlog.contextvars` bindings from the API process don't carry over. Each task must bind its own context vars (`job_id`, `user_id`, `task_type`) at the start of execution.

### Backwards compatibility
- Feature flag: `USE_CELERY` env var
- When unset: fall back to in-process `GpuQueue` (current behavior)
- This allows gradual rollout and easy rollback
- Phase 7 removes the flag and the old code path

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
      USE_CELERY: "1"

  worker:
    build: .
    command: celery -A songmaker_cli.celery_app worker --concurrency=1
    environment:
      REDIS_URL: redis://redis:6379/0
      DATABASE_URL: postgresql://...
      ACESTEP_DEVICE: cuda:0
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]

  beat:
    build: .
    command: celery -A songmaker_cli.celery_app beat
    environment:
      REDIS_URL: redis://redis:6379/0
```

## Testing

- Unit tests: mock `generate_task.delay()`, verify correct args
- Integration test: real Celery worker + Redis in Docker, submit job, poll until complete
- Timeout test: submit task that sleeps forever, verify SIGKILL after `time_limit`
- Recovery test: kill worker mid-task, verify job redelivered and idempotency check works
- Idempotency test: manually set job to "completed", submit task, verify no-op
- Existing test suite: runs unchanged (tests call `run_generation_job()` directly, not via queue)
- structlog test: verify task logs include `job_id` context
