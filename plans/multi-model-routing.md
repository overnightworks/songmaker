# Multi-Model Generation Routing

> **Status: FUTURE** — depends on having multiple GPUs or model-switching capability

## Goal

Users select which model to use when generating. Jobs are routed to the correct model backend. The system knows which models are available and healthy.

## Current State

- Single ACE-Step server, single arq worker, single GPU
- `model_mode` on presets is informational only — doesn't influence routing
- All jobs go to the same worker regardless of params
- Admin `available_models` table controls which models users can create presets for
- Health endpoint reports one active model from the single ACE-Step server

## Architecture Options

### Option A: One worker per model

Each GPU runs its own ACE-Step server + arq worker. Jobs are routed to the right queue.

```
User generates (model_mode=turbo)
  → API enqueues to "arq:queue:turbo"
  → Worker-turbo picks it up
  → ACE-Step-turbo processes it

User generates (model_mode=sft)
  → API enqueues to "arq:queue:sft"
  → Worker-sft picks it up
  → ACE-Step-sft processes it
```

**Pros:** Simple routing (queue per model), no model switching, workers are independent
**Cons:** Requires one GPU per model, no sharing

### Option B: Model-switching single worker

One worker, one GPU. Worker loads/unloads models on demand. Similar to current `prepare_generate_mode` / scorer mode switching.

```
User generates (model_mode=turbo)
  → API enqueues to single queue with model_mode tag
  → Worker checks: is turbo loaded?
  → If not: stop current model, load turbo, wait for health
  → Process job
```

**Pros:** Works with one GPU, no infrastructure change
**Cons:** Model switching takes 30-60s, blocks all other jobs during switch. Thrashing if users alternate models.

### Recommendation

**Option A for production, Option B as interim.** Option B already partially exists (ACE-Step manager can restart with different config). Option A is the clean solution when you have 2+ GPUs.

---

## Phase 1: Model tag on generations (prerequisite)

Store which model produced each generation, so users know what they got.

| File | Change |
|------|--------|
| `db/models.py` | Add `model_mode: str` column to `Generation` |
| `db/migrations/` | Alembic migration |
| `jobs.py` | Save `model_mode` when creating generation record |
| `api_models/songs.py` | Include `model_mode` in `GenerationResponse` |
| Frontend | Show model badge on generation cards |

---

## Phase 2: Model selection on generate

User chooses model when hitting Generate. Defaults to their preset's model.

| File | Change |
|------|--------|
| `api_models/songs.py` | `GenerateRequest.model_mode: str` (required or default from preset) |
| `generation_api.py` | Validate `model_mode` against active models. Pass to worker |
| Frontend `+page.svelte` | Model selector next to Generate button (if multiple active models) |

---

## Phase 3: Health-based model discovery

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

## Phase 4: Job routing (Option A)

Route jobs to model-specific queues.

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

## Phase 5: Job routing (Option B — single GPU fallback)

If only one GPU, worker switches models on demand.

| File | Change |
|------|--------|
| `worker.py` | Before processing job, check if requested model matches loaded model. If not, call `acestep_manager.switch_model(mode)` |
| `acestep_manager.py` | Add `switch_model(mode)` — stop current server, start with new config, wait for health |
| `constants.py` | Model config paths: `{"sft": "acestep-v15-sft", "turbo": "acestep-v15-turbo"}` |

### Optimization: batch by model

Sort queue by model_mode to minimize switches:
```
Queue: [sft, sft, turbo, sft, turbo]
Reorder: [sft, sft, sft, turbo, turbo]  → 1 switch instead of 4
```

This requires custom job scheduling, not default arq FIFO.

---

## Phase 6: Song model_mode persistence

Store the model used for generation on the song version, so the UI can warn about mismatches.

| File | Change |
|------|--------|
| `db/models.py` | Add `model_mode: str \| None` to `Version` |
| `song_api.py` | When saving generation_params, also save model_mode |
| Frontend | If song's model_mode doesn't match an active model, show warning on Generate button |

---

## Phase 7: Distributed workers

Workers run on remote GPU servers instead of the web server's machine. Multiple workers can serve the same model for horizontal scaling.

### What needs to change

**ACE-Step URL (small):**
Currently hardcoded to `localhost:8001`. Each worker manages its own ACE-Step subprocess, so this stays as-is — the worker and its ACE-Step server are co-located on the same GPU machine. No change needed.

**Audio file storage (medium):**
Currently audio files are written to a local `data/audio/` directory shared between web server and worker via Docker volume. With remote workers, this breaks.

Options:
- **A) Object storage (S3/MinIO):** Worker uploads audio after generation, web server serves from storage. Clean, standard, works at any scale.
- **B) Shared NFS mount:** All machines mount the same network filesystem. Simple but adds infrastructure dependency and latency.
- **C) Worker pushes via API:** Worker uploads audio to the web server via HTTP after generation. No shared storage needed, but adds an endpoint and network transfer.

**Recommendation:** Option C for simplicity. Add `POST /api/internal/upload-audio` (worker-authenticated) that accepts the audio file. Migrate to S3 later if file volume grows. Option B works if all machines are on the same network.

| File | Change |
|------|--------|
| `generate.py` | After writing audio files, upload to web server (or S3) |
| `server.py` or new `internal_api.py` | Internal upload endpoint (worker auth via shared secret) |
| `audio_io.py` | Abstract file storage behind interface (local / S3 / remote) |

**Database access (none):**
Workers already connect to PostgreSQL and Redis via network URLs. Remote workers just need `DATABASE_URL` and `REDIS_URL` pointing to the web server's DB/Redis. No code change.

**Worker registration:**
Workers register in Redis on startup with their model, host, and health status. The web server reads these to populate `available_models` automatically.

```
Redis key: songmaker:worker:{worker_id}
Value: { "model_mode": "sft", "host": "gpu-1.internal", "last_seen": "...", "jobs_running": 0 }
TTL: 60s (auto-expires if worker dies)
```

| File | Change |
|------|--------|
| `worker.py` | On startup and periodically, write worker info to Redis |
| `health_api.py` | Read all `songmaker:worker:*` keys to report available capacity |
| `settings_api.py` | Auto-update `available_models.is_active` based on registered workers |

### Deployment (example)

```
Web server (no GPU):
  - songmaker-web (FastAPI)
  - PostgreSQL
  - Redis
  - Prometheus + Grafana

GPU server 1:
  - songmaker-worker (ACESTEP_CONFIG_PATH=acestep-v15-sft)
  - ACE-Step server (managed by worker)
  - Connects to: Redis @ web-server, PostgreSQL @ web-server

GPU server 2:
  - songmaker-worker (ACESTEP_CONFIG_PATH=acestep-v15-turbo)
  - ACE-Step server (managed by worker)
  - Connects to: Redis @ web-server, PostgreSQL @ web-server
```

---

## Phase 8: Horizontal scaling (multiple workers per model)

Run N workers with the same model to handle concurrent users. arq handles this natively.

### How it works

arq workers listening on the same queue compete for jobs. If 3 SFT workers are running, up to 3 SFT jobs run in parallel. No code change needed for basic round-robin — arq does this out of the box.

```
Queue: arq:queue:sft
  ← Worker-sft-1 (gpu-server-1) picks job A
  ← Worker-sft-2 (gpu-server-2) picks job B
  ← Worker-sft-3 (gpu-server-3) picks job C
```

### What needs to change

**Rate limiting:**
Current `MAX_QUEUE_DEPTH=10` is a global limit. With 3 workers, you'd want a higher limit. Make queue depth configurable per model or auto-scale based on registered workers.

| File | Change |
|------|--------|
| `api_helpers.py` | Queue depth limit = base × number of healthy workers for that model |
| `health_api.py` | Report per-model capacity (workers × max_jobs) |

**Scoring:**
Currently scoring runs on the same worker as generation (GPU needed for some scorers). With horizontal scaling, scoring jobs should go to whichever worker is free — they already do via the shared queue.

**Monitoring:**
Per-worker metrics so you can see which GPU is busy/idle.

| File | Change |
|------|--------|
| `worker.py` | Include `worker_id` in job metrics |
| `health_api.py` | Report per-worker stats from Redis |
| Grafana | Dashboard showing worker load distribution |

### Deployment (example — 3 SFT workers)

```yaml
# On gpu-server-1
songmaker-worker:
  environment:
    ACESTEP_CONFIG_PATH: acestep-v15-sft
    ARQ_QUEUE_NAME: arq:queue:sft
    REDIS_URL: redis://web-server:6379/0
    DATABASE_URL: postgresql://user:pass@web-server/songmaker
    WORKER_ID: sft-1

# On gpu-server-2 (identical config, different WORKER_ID)
songmaker-worker:
  environment:
    ACESTEP_CONFIG_PATH: acestep-v15-sft
    ARQ_QUEUE_NAME: arq:queue:sft
    REDIS_URL: redis://web-server:6379/0
    DATABASE_URL: postgresql://user:pass@web-server/songmaker
    WORKER_ID: sft-2
```

No code change needed for this to work. arq handles the distribution.

---

## Priority

Phase 1 (model tag) → Phase 2 (model selection UI) → Phase 3 (health discovery) → Phase 4 (queue routing) → Phase 7 (distributed) → Phase 8 (horizontal scaling)

Phase 5 (single-GPU model switching) is an alternative to Phase 4+7 for budget setups.
Phase 6 (song model persistence) can happen anytime after Phase 2.

## Phase 9: Database role separation

Currently one PostgreSQL user (`songmaker`) for everything. With remote workers, a compromised worker has full DB access. Separate roles limit blast radius.

### Roles

| Role | Access | Used by |
|------|--------|---------|
| `songmaker_web` | Read/write all tables | Web server (FastAPI) |
| `songmaker_worker` | Read/write: jobs, generations, scores, generation_presets. Read-only: songs, versions, albums, users | arq worker |
| `songmaker_migrate` | Full DDL (CREATE, ALTER, DROP) + read/write all | Alembic migrations only |

### Changes

| File | Change |
|------|--------|
| `scripts/setup_db_roles.sql` | New: SQL script creating roles + grants |
| `.env.docker.example` | Separate `DATABASE_URL_WEB`, `DATABASE_URL_WORKER`, `DATABASE_URL_MIGRATE` |
| `db/engine.py` | `init_db()` uses `DATABASE_URL_MIGRATE` for migrations, returns session factory with `DATABASE_URL_WEB` or `DATABASE_URL_WORKER` |
| `worker.py` | Uses `DATABASE_URL_WORKER` |
| `server.py` | Uses `DATABASE_URL_WEB` |
| `docker-compose.yml` | Pass different URLs to web vs worker |

### Setup script (example)

```sql
-- Run once as postgres superuser
CREATE ROLE songmaker_web LOGIN PASSWORD 'web_pass';
CREATE ROLE songmaker_worker LOGIN PASSWORD 'worker_pass';
CREATE ROLE songmaker_migrate LOGIN PASSWORD 'migrate_pass';

-- Web: full read/write
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO songmaker_web;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO songmaker_web;

-- Worker: limited tables
GRANT SELECT, INSERT, UPDATE ON jobs, generations, scores, generation_presets TO songmaker_worker;
GRANT SELECT ON songs, versions, albums, users TO songmaker_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO songmaker_worker;

-- Migrate: full DDL
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO songmaker_migrate;
GRANT ALL PRIVILEGES ON SCHEMA public TO songmaker_migrate;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO songmaker_migrate;
```

### Backward compatibility

If only `DATABASE_URL` is set (no role separation), all services use it — identical to today. Role separation is opt-in.

---

## Constraints

- arq supports custom queue names via `_queue_name` parameter on `enqueue_job`
- arq natively supports multiple workers on the same queue (horizontal scaling)
- Current `max_jobs=1` on worker stays — GPU jobs are sequential per worker
- Scoring always runs on the generation worker (no separate routing needed)
- Rate limiting is per-user, not per-model — no change needed
- ACE-Step startup takes 30-60s — model switching has visible latency
- Remote workers need network access to Redis and PostgreSQL
- Audio file transfer is the main distributed challenge (local volume doesn't work remotely)
