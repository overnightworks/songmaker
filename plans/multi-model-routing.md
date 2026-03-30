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

## Priority

Phase 1 (model tag on generations) → Phase 2 (model selection UI) → Phase 3 (health discovery) → Phase 4 or 5 (routing)

Phase 6 can happen anytime after Phase 2.

## Constraints

- arq supports custom queue names via `_queue_name` parameter on `enqueue_job`
- Current `max_jobs=1` on worker stays — GPU jobs are sequential per worker
- Scoring always runs on the generation worker (no separate routing needed)
- Rate limiting is per-user, not per-model — no change needed
- ACE-Step startup takes 30-60s — model switching has visible latency
