# Multi-Model Generation Routing

> **Status: DEFERRED** — Single-GPU dynamic model switching is shipped (`AceStepManager.switch_model`, per-generation `model_mode`, model dropdown, worker auto-switch). This plan covers multi-GPU routing and horizontal scaling only. It is mutually exclusive with `switch_model`: when this lands, `switch_model` and its lock/persistence machinery get deleted.
>
> **Triggers to revisit (any one is enough):**
> 1. A second GPU is added to the deployment.
> 2. Sustained multi-user load on a single GPU — the moment two users with different model preferences hit the worker concurrently, `switch_model` thrashes (30–90s dead time per swap).
> 3. A `switch_model` production bug costs more than an hour to debug — signal that the state machine has outgrown its single-GPU usefulness.
>
> Until one of these fires, do not build this plan and do not extend `switch_model`. Pick one strategy per deployment.

## Goal

Route generation jobs to model-specific workers across multiple GPUs. Scale horizontally with multiple workers per model.

## Current State

Already shipped:
- Per-generation model dropdown in song editor
- Generate request carries `model_mode`
- Worker auto-switches model if loaded model doesn't match requested (single-GPU, blocking)
- Model tag on every generation (`model_mode` column on `Generation`)
- Model capability metadata in API
- Parameter visibility adapts to selected model

What we WON'T have until this plan lands: multi-GPU routing, automatic health discovery, distributed workers. The UI already works correctly — this plan removes the switching overhead by running multiple models simultaneously on separate workers/GPUs.

---

## Phase 1: Health-Based Model Discovery

Replace admin-only model toggles with automatic discovery from running servers.

| File | Change |
|------|--------|
| `worker.py` | On startup, register model in `available_models` table with health status |
| `lifecycle.py` or new `model_registry.py` | Background task polls model servers, updates availability |
| `health_api.py` | Report all known models with health status |
| `settings_api.py` | `available_models.is_active` auto-set from health, admin can still force-disable |

### Health reporting

Each worker reports to Redis on startup:
```
songmaker:model:{model_mode}:health = { "worker_id": "...", "last_seen": "...", "jobs_running": 0 }
```

The API reads these keys to determine which models are available. TTL-based: if a worker doesn't report in 60s, model is marked unhealthy.

---

## Phase 2: Job Routing (Multi-GPU)

Route jobs to model-specific queues. One worker per GPU, each running a different model.

| File | Change |
|------|--------|
| `worker.py` | `WorkerSettings.queue_name` derived from model config (e.g., `arq:queue:sft`) |
| `generation_api.py` | Enqueue to model-specific queue: `pool.enqueue_job("generate", ..., _queue_name=queue)` |
| `docker-compose.yml` | One worker service per model, each with different `ACESTEP_CONFIG_PATH` |
| `arq_pool.py` | Support multiple queue connections or use arq's queue routing |

### Docker Compose (example)

```yaml
songmaker-worker-sft:
  build: { dockerfile: Dockerfile.worker }
  environment:
    ACESTEP_CONFIG_PATH: acestep-v15-sft
    ARQ_QUEUE_NAME: arq:queue:sft
  deploy:
    resources:
      reservations:
        devices:
          - capabilities: [gpu]
            device_ids: ["0"]

songmaker-worker-turbo:
  build: { dockerfile: Dockerfile.worker }
  environment:
    ACESTEP_CONFIG_PATH: acestep-v15-turbo
    ARQ_QUEUE_NAME: arq:queue:turbo
  deploy:
    resources:
      reservations:
        devices:
          - capabilities: [gpu]
            device_ids: ["1"]
```

---

## Phase 3: Distributed Workers

Workers run on remote GPU servers. Multiple workers can serve the same model.

### What needs to change

**Audio file storage:**
Currently audio files are in a local `data/audio/` directory shared via Docker volume. With remote workers, this breaks.

Options:
- **A) Object storage (S3/MinIO):** Worker uploads audio after generation, web server serves from storage.
- **B) Shared NFS mount:** All machines mount the same network filesystem.
- **C) Worker pushes via API:** Worker uploads audio to web server via HTTP after generation.

**Recommendation:** Option C for simplicity. Add `POST /api/internal/upload-audio` (worker-authenticated). Migrate to S3 later if file volume grows.

| File | Change |
|------|--------|
| `generate.py` | After writing audio files, upload to web server (or S3) |
| `server.py` or new `internal_api.py` | Internal upload endpoint (worker auth via shared secret) |
| `audio_io.py` | Abstract file storage behind interface (local / S3 / remote) |

**Database access:** No change — workers already connect via network URLs.

**Worker registration:** Workers register in Redis on startup with their model, host, and health status.

```
Redis key: songmaker:worker:{worker_id}
Value: { "model_mode": "sft", "host": "gpu-1.internal", "last_seen": "...", "jobs_running": 0 }
TTL: 60s (auto-expires if worker dies)
```

---

## Phase 4: Horizontal Scaling

Run N workers with the same model. arq handles this natively — workers on the same queue compete for jobs.

### What needs to change

**Rate limiting:** Current `MAX_QUEUE_DEPTH=10` is global. With N workers, scale limit: queue depth = base × number of healthy workers for that model.

**Monitoring:** Per-worker metrics so you can see which GPU is busy/idle.

| File | Change |
|------|--------|
| `api_helpers.py` | Queue depth limit = base × number of healthy workers for that model |
| `worker.py` | Include `worker_id` in job metrics |
| `health_api.py` | Report per-worker stats from Redis |

---

## Phase 5: Database Role Separation

Separate PostgreSQL roles to limit blast radius of a compromised remote worker.

| Role | Access | Used by |
|------|--------|---------|
| `songmaker_web` | Read/write all tables | Web server (FastAPI) |
| `songmaker_worker` | Read/write: jobs, generations, scores, generation_presets. Read-only: songs, versions, albums, users | arq worker |
| `songmaker_migrate` | Full DDL | Alembic migrations only |

Opt-in: if only `DATABASE_URL` is set, all services use it (identical to today).

---

## Priority

Phase 1 (health discovery) → Phase 2 (queue routing) → Phase 3 (distributed) → Phase 4 (horizontal scaling) → Phase 5 (DB roles)

All phases depend on acestep-modes Phase 1 being complete first.

## Constraints

- arq supports custom queue names via `_queue_name` parameter on `enqueue_job`
- arq natively supports multiple workers on the same queue (horizontal scaling)
- Current `max_jobs=1` on worker stays — GPU jobs are sequential per worker
- Scoring always runs on the generation worker (no separate routing needed)
- Rate limiting is per-user, not per-model — no change needed
- ACE-Step startup takes 30-60s — model switching has visible latency
- Remote workers need network access to Redis and PostgreSQL
- Audio file transfer is the main distributed challenge
