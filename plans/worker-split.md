# Worker Split: Queue-Per-Type with Config-Driven Device Selection

## Goal

Split the monolithic arq worker into separate workers per job type, with API-layer routing and configurable device selection. Foundation for multi-modal scaling.

## Architecture

```
                         ┌─ arq:queue:music   → Music Worker(s)   [GPU, ACE-Step]
API ─→ route by type ───┼─ arq:queue:scoring  → Scoring Worker(s) [GPU or CPU, Whisper/AudioBox]
                         └─ (chat is inline, no arq queue)
```

Each worker:
- Listens on one queue (configured via `WORKER_QUEUE` env var)
- Owns its subprocess lifecycle (ACE-Step or scorer)
- Has configurable `max_jobs` and device
- Recovers only its own job type on startup/shutdown

Chat stays inline in the API process (no arq). It already works this way — `chat_api.py` calls `acall_claude()` directly and updates the job status in the same request. No change needed.

## Decisions

| Decision | Answer | Rationale |
|----------|--------|-----------|
| Deployment strategy | Coordinated (brief downtime) | Single-user platform |
| GPU sharing | Config-driven (`SCORING_DEVICE` env var) | Operator matches config to hardware |
| Stale recovery | Per-type, separate lock keys | Workers don't interfere with each other |
| Health degraded | If any worker is down | Reduced capability = degraded |
| Music worker `max_jobs` | 2 (default, configurable) | One active in ACE-Step, one pre-fetched |
| Scoring worker `max_jobs` | 1 GPU / 2 CPU (default, configurable) | GPU scorers aren't internally queued |
| Model switching | Keep (ACE-Step HTTP reinitialize) | Clean feature, no VRAM coordination needed after split |
| VRAM coordination | Remove from application | `prepare_generate_mode()` scorer eviction deleted — separate workers, separate lifecycle |

## Queue and Redis Key Design

**New constants** (in `constants.py`):
```
ARQ_MUSIC_QUEUE_NAME = "arq:queue:music"
ARQ_SCORING_QUEUE_NAME = "arq:queue:scoring"
ARQ_MUSIC_HEALTH_KEY = "arq:queue:music:health-check"
ARQ_SCORING_HEALTH_KEY = "arq:queue:scoring:health-check"
RECOVERY_LOCK_MUSIC_KEY = "songmaker:recovery_lock:music"
RECOVERY_LOCK_SCORING_KEY = "songmaker:recovery_lock:scoring"
```

**Removed** (Phase 5): `ARQ_QUEUE_KEY`, `ARQ_HEALTH_KEY`, `RECOVERY_LOCK_KEY`

## SCORING_DEVICE Wiring

The scoring worker reads `SCORING_DEVICE` env var and passes it through to `run_scoring_job()`. The call chain:

1. `scoring_worker.score()` reads `os.environ.get("SCORING_DEVICE", "cpu")`
2. Passes to `run_scoring_job(..., device=device)`
3. `run_scoring_job()` passes to `PipelineConfig(device=device)`
4. `PipelineConfig.device` is used by each scorer's `@register()` decorator to decide execution device

This replaces the current `_detect_device()` in `jobs.py` which auto-detects CUDA. The env var gives explicit operator control.

## arq Health Key Convention

arq auto-generates health check keys as `{queue_name}:health-check`. Our constants must match this pattern exactly:
- `ARQ_MUSIC_QUEUE_NAME = "arq:queue:music"` → arq writes `"arq:queue:music:health-check"`
- `ARQ_SCORING_QUEUE_NAME = "arq:queue:scoring"` → arq writes `"arq:queue:scoring:health-check"`

The `ARQ_*_HEALTH_KEY` constants are derived, not independent. If you change the queue name, the health key changes.

## Phases

### Phase 1: Shared worker infrastructure (pure refactor, no behavior change)

Extract common code from `worker.py` into `worker_base.py` so both new workers can reuse it.

**Modify: `src/songmaker_cli/constants.py`**
- Add new queue name, health key, and recovery lock constants (listed above in "Queue and Redis Key Design")
- These are needed by Phase 2 workers, so must be added here

**New file: `src/songmaker_cli/worker_base.py`**

Extract from `worker.py`:
- `_get_db_factory()`, `_db_factory`, `_db_engine`, `_db_lock` — DB singleton
- `_audio_dir()`, `_data_dir()` — path helpers
- `TERMINAL_STATUSES` — terminal status set
- `JOB_TIMEOUT_SECONDS`, `DRAIN_TIMEOUT_SECONDS`, `HEALTH_CHECK_INTERVAL_SECONDS` — timeout constants
- `common_startup(ctx)` — env loading, logging config, Redis URL mismatch warning
- `common_shutdown(ctx, recovery_lock_key, job_type)` — per-type stale recovery, DB disposal
- `check_job_still_valid(job_id)` — checks if job is in terminal status (used by both generate and score tasks)

**Modify: `src/songmaker_cli/worker.py`**
- Import shared code from `worker_base` instead of defining locally
- No behavioral change — still one worker, one queue, same tasks

**New file: `tests/test_worker_base.py`**
- Test `check_job_still_valid()`, `_get_db_factory()` caching, `common_startup()` env loading

**Modify: `tests/test_worker.py`**
- Update imports to reference `worker_base` where functions moved

### Phase 2: Music worker + Scoring worker

**New file: `src/songmaker_cli/music_worker.py`**

```python
class MusicWorkerSettings:
    functions = [generate, reinitialize_acestep]
    on_startup = on_startup
    on_shutdown = on_shutdown
    queue_name = ARQ_MUSIC_QUEUE_NAME
    max_jobs = int(os.environ.get("MUSIC_MAX_JOBS", "2"))
    job_timeout = JOB_TIMEOUT_SECONDS
    job_completion_wait = DRAIN_TIMEOUT_SECONDS
    health_check_interval = HEALTH_CHECK_INTERVAL_SECONDS
    cron_jobs = [cron(cleanup_stale, minute={...}, second={0})]
```

Contains:
- `generate()` task — moved from `worker.py`
- `reinitialize_acestep()` task — moved from `worker.py`
- `_publish_acestep_status()` helper — moved from `worker.py`
- `cleanup_stale()` cron — recovers stale jobs with `type='generate'`
- `on_startup()` — calls `common_startup()`, initializes ACE-Step manager, publishes status, recovers stale generate jobs
- `on_shutdown()` — calls `common_shutdown()` with `job_type="generate"`, stops ACE-Step
- `_acestep_manager`, `_acestep_lock` globals — moved from `worker.py`

**New file: `src/songmaker_cli/scoring_worker.py`**

```python
class ScoringWorkerSettings:
    functions = [score]
    on_startup = on_startup
    on_shutdown = on_shutdown
    queue_name = ARQ_SCORING_QUEUE_NAME
    max_jobs = int(os.environ.get("SCORING_MAX_JOBS", "1"))
    job_timeout = JOB_TIMEOUT_SECONDS
    job_completion_wait = DRAIN_TIMEOUT_SECONDS
    health_check_interval = HEALTH_CHECK_INTERVAL_SECONDS
    cron_jobs = [cron(cleanup_stale, minute={...}, second={0})]
```

Contains:
- `score()` task — moved from `worker.py`
- `cleanup_stale()` cron — recovers stale jobs with `type='score'`
- `on_startup()` — calls `common_startup()`, initializes `ScorerProcess`, recovers stale score jobs
- `on_shutdown()` — calls `common_shutdown()` with `job_type="score"`, shuts down scorer subprocess

**Modify: `src/songmaker_cli/db/queries/jobs.py`**
- Add `recover_stale_jobs_by_type(session, job_type)` — same as `recover_stale_jobs()` but filtered by `Job.type`
- Add `recover_stale_jobs_by_age_and_type(session, job_type, threshold_seconds)` — same as `recover_stale_jobs_by_age()` but filtered by `Job.type`
- Update `get_queue_position()` to accept optional `job_type` filter — with separate queues, position should reflect only jobs of the same type
- Export new functions from `db/queries/__init__.py`

**Modify: `src/songmaker_cli/worker.py`**
- Keep as backwards-compatible shim during transition
- Import `generate`, `score`, `reinitialize_acestep` from new modules
- `WorkerSettings` unchanged (listens on default `arq:queue`)
- Add deprecation log warning on startup

**Modify: `src/songmaker_cli/acestep_manager.py`**
- Remove `_release_scorer_gpu()` call from `prepare_generate_mode()`
- Remove `verify_vram_freed()` call from `prepare_generate_mode()`
- Delete `_release_scorer_gpu()`, `clear_scoring_models()`, `verify_vram_freed()`, `gc_gpu()` — dead code after split, scorer lifecycle is now the scoring worker's responsibility
- `prepare_generate_mode()` simplifies to: ensure ACE-Step running + refresh cached model

**Modify: `src/songmaker_cli/jobs.py`**
- `run_scoring_job()`: replace `_detect_device()` with explicit `device` parameter
- Delete `_detect_device()` — replaced by env-var-driven config in scoring worker
- Delete `_cleanup_gpu()` — scorer worker manages its own GPU lifecycle

**New tests:**
- `tests/test_music_worker.py` — generate task, reinitialize, startup/shutdown, cron
- `tests/test_scoring_worker.py` — score task, startup/shutdown, cron

**Modify: `tests/test_worker.py`**
- Reduce to testing backwards-compat shim only

### Phase 3: API routing + per-worker health checks

**Modify: `src/songmaker_cli/arq_pool.py`**
- Add `is_music_worker_healthy()` — checks `ARQ_MUSIC_HEALTH_KEY`
- Add `is_scoring_worker_healthy()` — checks `ARQ_SCORING_HEALTH_KEY`
- Add `get_music_queue_depth()` — `zcard(ARQ_MUSIC_QUEUE_NAME)`
- Add `get_scoring_queue_depth()` — `zcard(ARQ_SCORING_QUEUE_NAME)`
- Keep `is_worker_healthy()` and `get_queue_depth()` checking old keys during transition

**Modify: `src/songmaker_cli/generation_api.py`**
- `api_generate_song`: change `is_worker_healthy()` → `is_music_worker_healthy()`
- `api_generate_song`: change `pool.enqueue_job("generate", ...)` → `pool.enqueue_job("generate", ..., _queue_name=ARQ_MUSIC_QUEUE_NAME)`
- `api_score_generation`: change `is_worker_healthy()` → `is_scoring_worker_healthy()`
- `api_score_generation`: change `pool.enqueue_job("score", ...)` → `pool.enqueue_job("score", ..., _queue_name=ARQ_SCORING_QUEUE_NAME)`

**Modify: `src/songmaker_cli/settings_api.py`** (reinitialize ACE-Step endpoint)
- Route reinitialize to music queue: `pool.enqueue_job("reinitialize_acestep", _queue_name=ARQ_MUSIC_QUEUE_NAME)`

**Modify: `src/songmaker_cli/health_api.py`**
- Report per-worker health:
  ```json
  {
    "music_worker": "running",
    "scoring_worker": "stopped",
    "status": "degraded"
  }
  ```
- `status` = "degraded" if either worker is down, "ok" if both up
- Keep `worker` field as aggregate for backwards compat during transition
- Report per-queue depths: `music_queue_depth`, `scoring_queue_depth`

**Modify: `tests/test_rate_limit.py`**
- Update `_mock_arq()` to mock `is_music_worker_healthy` and `is_scoring_worker_healthy`

### Phase 4: Docker Compose

**Modify: `docker-compose.yml`**
- Replace `songmaker-worker` with two services:

```yaml
songmaker-music-worker:
  build:
    context: .
    dockerfile: Dockerfile.worker
  command: ["uv", "run", "arq", "songmaker_cli.music_worker.MusicWorkerSettings"]
  environment:
    MUSIC_MAX_JOBS: "2"
    # ... same DB, Redis, ACE-Step env vars as current worker
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]

songmaker-scoring-worker:
  build:
    context: .
    dockerfile: Dockerfile.worker
  command: ["uv", "run", "arq", "songmaker_cli.scoring_worker.ScoringWorkerSettings"]
  environment:
    SCORING_DEVICE: "cpu"  # or "cuda" if enough VRAM / separate GPU
    SCORING_MAX_JOBS: "1"
    # ... same DB, Redis env vars
  # No GPU reservation when SCORING_DEVICE=cpu
```

**Modify: `docs/architecture.md`**
- Update worker section to reflect split architecture

### Phase 5: Cleanup (after stable rollout)

**Delete: `src/songmaker_cli/worker.py`** — backwards-compat shim no longer needed

**Modify: `src/songmaker_cli/arq_pool.py`**
- Remove `is_worker_healthy()` and `get_queue_depth()` (old key checks)

**Modify: `src/songmaker_cli/constants.py`**
- Remove `ARQ_QUEUE_KEY`, `ARQ_HEALTH_KEY`, `RECOVERY_LOCK_KEY`

**Modify: `src/songmaker_cli/health_api.py`**
- Remove `worker` aggregate field

**Delete: `tests/test_worker.py`** — replaced by `test_music_worker.py` and `test_scoring_worker.py`

## File Change Summary

| File | Action | Phase |
|------|--------|-------|
| `src/songmaker_cli/constants.py` | Modify (new queue keys) | 1 |
| `src/songmaker_cli/worker_base.py` | **Create** | 1 |
| `src/songmaker_cli/worker.py` | Modify → Delete | 1, 2, 5 |
| `src/songmaker_cli/music_worker.py` | **Create** | 2 |
| `src/songmaker_cli/scoring_worker.py` | **Create** | 2 |
| `src/songmaker_cli/acestep_manager.py` | Modify (simplify, delete VRAM code) | 2 |
| `src/songmaker_cli/jobs.py` | Modify (device param, delete _detect_device) | 2 |
| `src/songmaker_cli/db/queries/jobs.py` | Modify (type-filtered recovery + queue_position) | 2 |
| `src/songmaker_cli/db/queries/__init__.py` | Modify (re-export) | 2 |
| `src/songmaker_cli/arq_pool.py` | Modify (per-worker health) | 3 |
| `src/songmaker_cli/generation_api.py` | Modify (routing) | 3 |
| `src/songmaker_cli/settings_api.py` | Modify (reinitialize routing) | 3 |
| `src/songmaker_cli/health_api.py` | Modify (per-worker status) | 3 |
| `docker-compose.yml` | Modify (two worker services) | 4 |
| `docs/architecture.md` | Modify | 4 |
| `tests/test_worker_base.py` | **Create** | 1 |
| `tests/test_music_worker.py` | **Create** | 2 |
| `tests/test_scoring_worker.py` | **Create** | 2 |
| `tests/test_worker.py` | Modify → Delete | 2, 5 |
| `tests/test_rate_limit.py` | Modify (mock targets) | 3 |

## Deployment Steps

1. Build new Docker images (same Dockerfile, different entrypoints)
2. Stop existing `songmaker-worker` container
3. Run `alembic upgrade head` (no new migrations for this change)
4. Start `songmaker-music-worker` and `songmaker-scoring-worker`
5. Verify via `/health` endpoint that both workers report "running"
6. Monitor for one day, then proceed to Phase 5 cleanup

## Risks

| Risk | Mitigation |
|------|------------|
| Rolling deploy gap (new API routes to new queues, old worker on old queue) | Coordinated deploy — stop old, start new |
| Test mock path changes break tests | Mechanical — update `patch()` targets, run full suite |
| `prepare_generate_mode()` simplification breaks generation | Test ACE-Step reinitialize flow after removal of scorer eviction |
| `max_jobs=2` on music worker causes unexpected behavior | Pre-fetched task just polls ACE-Step, low risk. Configurable via env var. |

## Adding a New Modality (future)

1. Write task function (e.g. `generate_image()`)
2. Add queue constant (`ARQ_IMAGE_QUEUE_NAME`)
3. Add health check function (`is_image_worker_healthy()`)
4. Add API routing (`pool.enqueue_job("generate_image", ..., _queue_name=ARQ_IMAGE_QUEUE_NAME)`)
5. Create worker module (`image_worker.py` with `ImageWorkerSettings`)
6. Add Docker Compose service
7. No existing code changes needed
