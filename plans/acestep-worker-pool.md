# ACE-Step Worker Pool Architecture

> **STATUS: IMPLEMENTED** — All 7 phases shipped on `feat/acestep-worker-pool`.
> - Phase 1 (wrapper container, model cache, task store): c416194
> - Phase 2 (control plane registration + Redis state): 275518c
> - Phase 3 (cutover, delete acestep_manager): 74b8576
> - Phase 4 (admin Worker Pool + Model Registry panels): a1ca504
> - Phase 5 (UI-driven downloads): a0e5136 + 574c84c + 7ab326a
> - Phase 6 (observability + refcount/pin/restart): 6780f9e + 550e249 + 8d285e5 + ed7ee07
> - Phase 7 (cleanup sweep): this commit
>
> Phase 8 (image architecture refactor) is a separate follow-up — see its own sub-plan.

> **Final destination after plan approval**: this content gets saved to `plans/acestep-worker-pool.md` as the first step of implementation, and `plans/multi-model-routing.md` gets marked **STATUS: SUPERSEDED** with a pointer to this plan.

## Plan Revisions (2026-04-07)

Reviewed and revised after implementation analysis. Changes from the original draft:

1. **Downloads moved to the acestep-worker container.** Original draft put `download_model` in the music-worker, contradicting Phase 3's "music-worker has no model weights mount, no acestep deps". The acestep-worker is the natural owner — it has the volume mount, the deps, and the right trust boundary.
2. **Generation dispatch is async via SSE, not long-lived synchronous HTTP.** Worker `/generate` returns `{task_id}` immediately and runs the generation in an asyncio background task. Scheduler subscribes to `GET /tasks/{task_id}/stream` (SSE) for `progress`/`done`/`error` events. If the SSE connection drops mid-generation, scheduler reconnects to the **same** `task_id` and resumes — server-side task state survives. A 5-10 minute synchronous HTTP call would die on any proxy hop or network blip and waste the whole generation.
3. **Ephemeral worker state moved to Redis with TTL.** PostgreSQL `acestep_workers` table keeps stable **identity** (id, host, port, gpu_id, vram_total_gb, registered_at). Redis holds the **rapidly-changing fields** (loaded_models, queue_depth, vram_used_gb, target_loading, available_modes) with a 15s TTL. Auto-expiry replaces the stale-sweep cron entirely.
4. **Atomic `queue_depth` increment in the scheduler.** Scheduler `INCR`s the Redis queue_depth key on dispatch and `DECR`s on completion. Prevents two concurrent dispatches both picking the same idle worker because heartbeats lag by up to 5s.
5. **`WorkerInfo`, `GenerateTaskResponse`, and SSE event payloads are first-class Pydantic models in Phase 2.** No mid-implementation guesswork.
6. **`docs/security.md` work promoted from Phase 6 to Phase 2.** Trust boundaries (internal token, control-plane endpoints sharing a process with the public API) get documented in the same PR that introduces them.
7. **Open question added: subprocess-per-loaded-model vs single subprocess holding multiple models** when LRU > 1 becomes real. Don't decide now, but measure during Phase 1 so the answer is data-backed when it matters.
8. **`/api/admin/workers/{id}/load_model` flow clarified.** It enqueues an arq job; the job handler proxies to the worker's `/load_model` and surfaces progress via the existing `/api/jobs/{job_id}/stream` SSE endpoint. Frontend reuses the same SSE client it already uses for generation job progress.

**Source-code accuracy fixes** (verified against the current tree):

- `AceStepStatusResponse` lives at [api_models/settings.py:188](../src/songmaker_cli/api_models/settings.py#L188), **not** `api_models/admin.py` (which does not exist). Files Touched updated. New worker/registry models go in a new `api_models/workers.py`.
- `is_model_downloaded()` does **not** exist in the codebase today. New helper — lives in `acestep_worker/` and checks `MODEL_CONFIG_PATHS` against the filesystem.
- Existing SSE endpoint is [generation_api.py:449](../src/songmaker_cli/generation_api.py#L449). The new worker-internal `/tasks/{task_id}/stream` reuses the same SSE shape but is on the worker container, not the web container.
- Stale-worker reaper pattern follows [lifecycle.py:111](../src/songmaker_cli/lifecycle.py#L111) `session_sync_loop` — except with the Redis TTL design from #3 above, no reaper is needed at all.

## Context

The user just hit a major UX confusion: toggled `XL-SFT ON` in admin, expected a model swap, the UI kept showing `acestep-v15-sft` as loaded, no feedback during the (eventual, user-triggered) 2-5 minute swap. Three concepts are conflated in the current UI:

1. **Downloaded** — safetensors weights exist on disk
2. **Available** — `available_models.is_active = True`; allowed in user dropdowns
3. **Loaded** — currently in GPU memory in the running ACE-Step subprocess

The current architecture runs ACE-Step as a subprocess **inside** the music-worker container, managed by `acestep_manager.py`. Switching = stop subprocess, change `ACESTEP_CONFIG_PATH`, restart subprocess. Status published to Redis with 150 s TTL. Heartbeat overwrites loading state mid-switch. The "subprocess inside a container that manages another subprocess" pattern is the root cause — docker already does container lifecycle, we're reinventing it badly.

We considered four options:

- **A** — patch UX only (~2-3 days). Solves today's pain, leaves architecture unchanged.
- **B** — single ACE-Step container, restart-in-place (~2-3 days). Cleaner than A, doesn't scale to multi-GPU.
- **C** — container per model (~3-5 days). Multi-GPU works, but model identity baked into compose, switching = recreate.
- **D** — worker pool with stateless scheduler (~1 week scoped). The user explicitly chose this. **Recommended.**

There is also an existing `plans/multi-model-routing.md` plan that proposes per-model arq queues. **This plan supersedes that one.** Comparison:

| Aspect | This plan (D) | multi-model-routing.md |
|---|---|---|
| Worker identity | First-class DB entity, observable | Implicit arq queue consumer |
| Multi-model-per-GPU | Built in (LRU cache, future-ready) | One model per worker process |
| Model swap latency | HTTP `/load_model` (~5 s overhead) | docker recreate (~30 s overhead) |
| Admin UX | Worker Pool + Model Registry panels | Unaddressed |
| Failure recovery | Scheduler routes around dead workers | Per-queue stalls until worker back |
| Operational tooling | Custom (admin UI is the tool) | Free from arq CLI |
| New code | ~600 lines + tests | ~250 lines + tests |
| Future-proof for cloud / k8s | Yes (workers as Deployments) | Partial |

Choosing D is the architectural decision. **The reason it's the right call** despite being more code: every existing UX bug stems from the implicit nature of the current architecture. First-class workers fix it at the root. The cost (more lines, more moving parts) is paid once; the benefit (no UI lying, no `_switch_lock` debugging, no docker recreates from inside containers) compounds.

### Architectural shape

- **Workers are stateful peer containers**, one per GPU. They persist across model swaps. They expose `load_model` / `evict_model` / `generate` (async, returns task_id) / `tasks/{id}/stream` (SSE) / `download_model` HTTP endpoints. They self-register to the control plane (PG) and heartbeat to Redis.
- **The control plane lives in the web container.** Workers POST `/register` once (writes the stable identity row in `acestep_workers`) and then heartbeat by writing their ephemeral state directly to Redis with a 15s TTL. Web reads PG + Redis to assemble the admin view.
- **The scheduler lives in the music-worker container.** Stateless picker that reads worker identity from PG, ephemeral state from Redis, atomically increments `queue_depth` on dispatch, and uses SSE to consume the worker's task stream. Replaces `acestep_manager.py`.
- **The admin UI shows two panels**: Worker Pool (physical capacity) and Model Registry (data catalog). The "loaded" relationship is the edge between them.

### What this plan deliberately does **not** do

- Replace arq for the outer generation queue. arq still owns job persistence, retries, dead-letter. The scheduler runs **inside** an arq job handler.
- Touch `acestep_engine`. It's small, well-scoped, and becomes the worker→ACE-Step subprocess HTTP client (its current role).
- Add Kubernetes / mTLS / service mesh. Single-node for now, k8s-shaped if you ever migrate.

```
┌──────────────────────────────────────────────────────────┐
│  songmaker-web (FastAPI)                                  │
│   ├─ /api/admin/workers       (reads PG + Redis)          │
│   ├─ /api/admin/registry      (reads PG + Redis)          │
│   └─ /api/internal/workers/register  ← workers POST 1×    │
│                                                            │
│  PostgreSQL: acestep_workers (stable identity only)       │
└──────────────────────────────────────────────────────────┘
                                       ▲
                                       │ register (once on startup)
                                       │
┌──────────────────────────┐    ┌──────────────────────────┐
│ acestep-worker-0 (GPU 0) │    │ acestep-worker-1 (GPU 1) │  ← future
│  wrapper.py              │    │  (added later, zero code) │
│   └─ ACE-Step subprocess │    │                          │
│  HTTP endpoints:         │    └──────────────────────────┘
│   POST /load_model               (sync, fast)             │
│   POST /evict_model              (sync, fast)             │
│   POST /generate                 → {task_id}              │
│   GET  /tasks/{id}/stream        SSE: progress|done|error │
│   POST /download_model           → {task_id}              │
│   GET  /loaded_models                                     │
│   GET  /health                                            │
└──────────────────────────┘
        │              ▲
        │ heartbeat    │ /load_model, /generate, SSE
        │ to Redis     │
        ▼              │
┌──────────────────┐   │
│  Redis           │   │
│  songmaker:      │   │
│   acestep:       │   │
│    worker:{id}   │ ← TTL 15s, auto-expires
│    queue:{id}    │ ← INCR/DECR, no TTL
└──────────────────┘   │
        ▲              │
        │ read state   │
        │              │
┌──────────────────────────────────────────────────────────┐
│  songmaker-music-worker (arq)                             │
│   └─ scheduler.py (stateless picker)                      │
│       └─ on generate job:                                 │
│           1. read identity from PG, ephemeral from Redis  │
│           2. pick worker (prefer-loaded, then least-busy) │
│           3. INCR Redis queue_depth atomically            │
│           4. POST /load_model if needed                   │
│           5. POST /generate → task_id                     │
│           6. SSE-subscribe /tasks/{id}/stream until done  │
│           7. DECR queue_depth in finally                  │
└──────────────────────────────────────────────────────────┘
```

## Branching

All work lives on **`feat/acestep-worker-pool`**, branched from `main`. Merge to `main` after Phase 4 is verified end-to-end (user-visible cutover complete). Phases 5 and 6 can ship as follow-up PRs from `main` once it's stable.

Intermediate phases on the feature branch are not expected to be production-runnable. The user has explicitly opted out of backwards compatibility — there is no rollback plan, no `pre-cutover` tag, no parallel old/new code paths. Phases are organizational milestones, not deployment milestones.

## Cross-cutting rules (apply to every phase)

1. **Tests ship with code in the same commit/phase.** No phase is "done" until its tests are written, passing, and coverage is at 100% on new code (per `feedback_review_rounds.md`). Defer-the-tests is not on the table.
2. **Phase verification commands** (`ruff` + targeted `pytest` + smoke check) **must pass green before merging the phase to the feature branch.**
3. **Docs are updated in the phase that changes them**, not deferred to Phase 6. `docs/architecture.md` in Phase 3 (cutover), `docs/security.md` in Phase 2 (token introduced), `docs/acestep.md` in Phase 6 (operator polish).
4. **`scripts/generate_types.py` runs at the end of every backend phase that touches `api_models/`.** Frontend types stay in sync with the backend contract.
5. **No comments in code** (per `feedback_code_standards.md`). Descriptive names only.

## Phases

Eight phases, organized as commit/PR-review boundaries on the feature branch. Phases 1–6 are the implementation; Phase 7 is a cross-cutting cleanup sweep; Phase 8 is an image architecture refactor (base images, drop venv bind mount) discovered during Phase 3 smoke test.

---

### Phase 1 — ACE-Step worker container + wrapper API

**Goal**: build the new acestep-worker container with the wrapper API, runnable standalone. No scheduler integration yet — the music-worker's old `acestep_manager.py` path still runs in parallel during this phase only because deleting it requires the scheduler from Phase 3. The two paths coexist on the feature branch only; main is unaffected.

**New top-level package** `acestep_worker/` (peer of `acestep_engine`, `audio_engine`, `songmaker_cli`):

| File | Purpose |
|---|---|
| `acestep_worker/__init__.py` | Package marker |
| `acestep_worker/wrapper.py` | FastAPI app exposing the worker endpoints |
| `acestep_worker/model_cache.py` | LRU cache that owns the loaded ACE-Step subprocess(es) |
| `acestep_worker/task_store.py` | In-memory async task store: holds running generation/download tasks, exposes async iterator for SSE consumers |
| `acestep_worker/heartbeat.py` | Background loop: writes ephemeral state to Redis with 15s TTL every 5s |
| `acestep_worker/registry_client.py` | One-shot self-registration with the control plane on startup (writes stable identity row in PG via `/api/internal/workers/register`) |
| `acestep_worker/downloads.py` | `download_model` task: snapshot_download wrapper + progress polling + `is_model_downloaded` helper |
| `acestep_worker/models.py` | Pydantic request/response models for the worker API |
| `acestep_worker/__main__.py` | Entry point: `python -m acestep_worker --port 8001` |
| `docker/acestep-worker.Dockerfile` | New image build, installs ACE-Step deps + huggingface_hub + the wrapper |
| `tests/acestep_worker/test_wrapper.py` | Endpoint tests with mocked subprocess |
| `tests/acestep_worker/test_model_cache.py` | LRU evict, load idempotency, capacity check |
| `tests/acestep_worker/test_task_store.py` | Task lifecycle, SSE replay-from-current-state on reconnect |
| `tests/acestep_worker/test_heartbeat.py` | Redis writes, TTL, restart resilience |
| `tests/acestep_worker/test_downloads.py` | Download success, partial recovery, idempotent skip, progress events |
| `tests/acestep_worker/test_registry_client.py` | Register retry on failure |

**Worker endpoints** (in `wrapper.py`):

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/load_model` | `{mode: "xl-sft"}` | `{loaded: ["xl-sft"], evicted: [], target_loading: null}` (sync, idempotent) |
| `POST` | `/evict_model` | `{mode: "xl-sft"}` | `{loaded: [...], evicted: ["xl-sft"]}` (sync) |
| `POST` | `/generate` | (full ACE-Step config) | `{task_id: "gen-..."}` immediately; runs in background |
| `POST` | `/download_model` | `{mode: "xl-base"}` | `{task_id: "dl-..."}` immediately; runs in background |
| `GET` | `/tasks/{task_id}/stream` | — | **SSE stream**: events `progress` (with %), `done` (with result payload), `error` (with message). Re-connectable: replays the current state on reconnect, then streams new events. |
| `GET` | `/tasks/{task_id}` | — | One-shot status snapshot (no streaming) — for non-SSE consumers and tests |
| `GET` | `/loaded_models` | — | `{loaded: ["xl-sft"], target_loading: null, queue_depth: 0, vram_used_gb: 12.4, vram_total_gb: 24.0, available_modes: ["sft", "turbo", "xl-sft"]}` |
| `GET` | `/health` | — | `{status: "ok"}` (200) or 503 |

**Why `/generate` is async:** a generation runs 5-10 minutes. A synchronous HTTP call held open for that long is fragile — any proxy, network blip, or reverse-proxy timeout drops it and discards the work. The task pattern keeps server-side state alive across reconnects: scheduler can disconnect from `/tasks/{id}/stream`, the generation keeps running, scheduler reconnects to the same `task_id` and resumes seeing events.

**Task store semantics**: tasks live in memory in `task_store.py`. Each task has a state machine (`pending` → `running` → `done`|`error`) and a list of events. The SSE endpoint sends a synthetic "current state" event on connect, then streams new events as they arrive. Tasks are garbage-collected 60s after reaching a terminal state.

**`/loaded_models` and `available_modes`**: workers report `available_modes` by calling `is_model_downloaded(mode)` (new helper in `acestep_worker/downloads.py`) for each entry in `MODEL_CONFIG_PATHS`. This is the filesystem source-of-truth. The web container reads this from Redis (heartbeat-published) to compute the registry's "downloaded" set — the web container itself **does not** need the checkpoints volume mount.

**`model_cache.py` design** — LRU cache (built in from day one even though N=1 today, because retrofitting locking semantics later is painful):

```python
class ModelCache:
    def __init__(self, vram_budget_gb: float, model_sizes: dict[str, float]):
        self._loaded: OrderedDict[str, LoadedModel] = OrderedDict()
        self._lock = asyncio.Lock()
        self._target_loading: str | None = None
        self._budget_gb = vram_budget_gb
        self._sizes = model_sizes

    async def load(self, mode: str) -> LoadResult:
        async with self._lock:
            if mode in self._loaded:
                self._loaded.move_to_end(mode)
                return LoadResult(loaded=list(self._loaded), evicted=[])
            self._target_loading = mode
            try:
                evicted = self._evict_for(mode)
                self._loaded[mode] = await self._load_subprocess(mode)
                return LoadResult(loaded=list(self._loaded), evicted=evicted)
            finally:
                self._target_loading = None
```

For a 24 GB GPU with one ~12 GB XL model, this collapses to "evict the previous, load the new". The cache shape is built in; multi-model becomes free when you upgrade hardware.

**Subprocess management**: today ACE-Step runs as a subprocess. The wrapper keeps that pattern — `LoadedModel` owns one subprocess per loaded model, started on `load`, killed on `evict`. Subprocess isolation is good (a model crash doesn't take down the wrapper). With LRU=1, this is just "kill old, start new". Same behavior as today's `acestep_manager.start/stop`, but owned by the worker container. **Open question** (see Open Questions section): when LRU > 1 lands, revisit whether N subprocesses or one subprocess holding multiple models is the right shape. Measure subprocess overhead in Phase 1.

**Pinning**: deferred to Phase 6. With LRU=1 it's a no-op. Stub the API but don't wire eviction logic.

**Heartbeat to Redis** (`heartbeat.py`): every 5s, the worker writes a hash to Redis under `songmaker:acestep:worker:{worker_id}` with `{loaded_models, target_loading, vram_used_gb, vram_total_gb, available_modes, last_heartbeat_at}` and sets a 15s TTL via `EXPIRE`. If the worker dies, the key naturally expires within 15s — no reaper cron needed. The `queue_depth` lives in a separate key `songmaker:acestep:queue:{worker_id}` (an integer), incremented/decremented atomically by the scheduler — no TTL on this one (the worker itself never writes it).

**`docker-compose.yml` changes** (additive, doesn't touch existing services yet):

```yaml
services:
  songmaker-acestep-worker-0:
    build:
      context: .
      dockerfile: docker/acestep-worker.Dockerfile
    deploy:
      resources:
        reservations:
          devices: [{driver: nvidia, device_ids: ['0'], capabilities: [gpu]}]
    environment:
      WORKER_ID: "acestep-worker-0"
      GPU_ID: "0"
      VRAM_BUDGET_GB: "22"
      CONTROL_PLANE_URL: "http://songmaker-web:8080"
      SONGMAKER_INTERNAL_TOKEN: "${SONGMAKER_INTERNAL_TOKEN}"
    volumes:
      - ./_models/acestep:/app/_models/acestep:ro
    depends_on:
      songmaker-web:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 15s
      timeout: 5s
      retries: 3
```

The existing music-worker container's ACE-Step subprocess management stays alive **on the feature branch** during this phase only. Phase 3 deletes it.

**`pyproject.toml`**: register `acestep_worker` as a new top-level package in the project's package config (peer of `acestep_engine`, `audio_engine`, `songmaker_cli`). Same `[tool.uv.sources]` / `packages` / `tool.hatch.build.targets.wheel` section that lists the existing packages.

**Phase 1 verification**:
```bash
ruff check acestep_worker/ tests/acestep_worker/
pytest tests/acestep_worker/ -q --cov=acestep_worker --cov-report=term-missing  # 100%
docker compose build songmaker-acestep-worker-0
docker compose up -d songmaker-acestep-worker-0
curl -X POST http://localhost:8001/load_model -d '{"mode": "sft"}'
curl http://localhost:8001/loaded_models
curl -X POST http://localhost:8001/generate -d '{...full config...}'  # returns {task_id}
curl -N http://localhost:8001/tasks/<task_id>/stream                   # SSE events until done
```

---

### Phase 2 — Control plane (registration + Redis ephemeral state)

**Goal**: web container accepts one-shot registrations; workers heartbeat directly to Redis with TTL; admin can see worker pool. Still no scheduler integration; generation still goes through the old path.

**DB migration** (alembic, in `src/songmaker_cli/db/migrations/versions/`):

```sql
CREATE TABLE acestep_workers (
    id TEXT PRIMARY KEY,                    -- "acestep-worker-0"
    host TEXT NOT NULL,                     -- "songmaker-acestep-worker-0" (docker DNS)
    port INTEGER NOT NULL,                  -- 8001
    gpu_id INTEGER,
    vram_total_gb REAL,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_register_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Stable identity only.** No status/loaded_models/queue_depth/heartbeat columns — those are pure ephemeral state and live in Redis. Rationale: writing to PG every 5s for state that's already volatile is the wrong primitive. Redis with TTL is.

**Redis keys** (managed entirely by the worker + scheduler, never touched directly by the web container's write path):

| Key | Type | Writer | Reader | TTL |
|---|---|---|---|---|
| `songmaker:acestep:worker:{worker_id}` | hash | worker heartbeat (5s) | web admin endpoints, scheduler | 15s |
| `songmaker:acestep:queue:{worker_id}` | int | scheduler INCR/DECR | scheduler, web admin endpoints | none (lives as long as the worker; orphaned keys self-clean on next worker restart via `DEL`) |

The hash fields: `loaded_models` (JSON list), `target_loading`, `vram_used_gb`, `available_modes` (JSON list), `last_heartbeat_at`.

**Status derivation** (computed in the read path, never persisted):
- `online` if `worker:{id}` Redis key exists AND `target_loading` is null
- `loading` if `worker:{id}` exists AND `target_loading` is non-null
- `offline` if PG row exists but `worker:{id}` Redis key has expired

**No reaper cron needed.** Redis TTL handles offline detection automatically.

**New backend files**:

| File | Purpose |
|---|---|
| `src/songmaker_cli/db/models.py` | **Extend**: add `AceStepWorker` SQLAlchemy ORM model matching the new `acestep_workers` table (identity columns only) |
| `src/songmaker_cli/db/queries/workers.py` | CRUD on `acestep_workers` identity table: `register_worker` (upsert), `list_worker_identities`, `get_worker_identity` |
| `src/songmaker_cli/db/queries/__init__.py` | Re-export the new query functions (per project convention in CLAUDE.md) |
| `src/songmaker_cli/redis_keys.py` (or extend `redis_client.py`) | Helpers: `get_worker_state(worker_id)`, `list_worker_states()`, `get_queue_depth(worker_id)`, `incr_queue_depth`, `decr_queue_depth`, `clear_queue_depth(worker_id)` (called by worker on its own startup to self-clean orphaned increments) |
| `src/songmaker_cli/api_models/workers.py` | Pydantic: `WorkerRegisterRequest`, `WorkerIdentity`, `WorkerEphemeralState`, `WorkerInfo` (joined identity + state, used by scheduler), `WorkerResponse` (admin-facing, joined), `WorkerPoolResponse`, `RegistryModelResponse`, `RegistryResponse`, `GenerateTaskResponse`, `WorkerTaskEvent` (SSE event payload) |
| `src/songmaker_cli/internal_api.py` | New router mounted under `/api/internal/`, shared-secret auth via dependency-injected token check at the **router level** (not per-endpoint) |

**Router-level token check** (concrete shape — copy this into `internal_api.py`):

```python
def verify_internal_token(x_internal_token: str = Header(...)) -> None:
    expected = os.environ["SONGMAKER_INTERNAL_TOKEN"]
    if not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(status_code=401, detail="invalid internal token")

internal_router = APIRouter(
    prefix="/api/internal",
    dependencies=[Depends(verify_internal_token)],
)
```

Adding a new endpoint to `internal_router` automatically inherits the token check. There is no way to forget it.

**The existing `available_models` PG table**: kept as-is. Its `is_active` column is still the source of truth for "admin allows this model in the dropdown". Its `is_active=True` rows for non-downloaded modes are now caught by the registry endpoint (which cross-references against worker heartbeats) and surfaced as "inactive: model files missing". The table is not extended, not migrated, not removed. **The new `acestep_workers` table is independent of it.**

**`WorkerInfo` shape** (the type returned by `pick_worker` in Phase 3):

```python
class WorkerInfo(BaseModel):
    id: str
    host: str
    port: int
    gpu_id: int | None
    vram_total_gb: float | None
    loaded_models: list[str]
    target_loading: str | None
    queue_depth: int
    available_modes: list[str]
    last_heartbeat_at: datetime | None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"
```

**Endpoints** in `internal_api.py`:

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/internal/workers/register` | `X-Internal-Token` | Worker registers on startup; upserts identity in PG by `worker_id`. Workers do **not** POST heartbeats here — heartbeats go straight to Redis. |

**Admin endpoints** (extend `admin_api.py`):

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/admin/workers` | admin | Joins PG identity rows with Redis ephemeral state, returns `WorkerPoolResponse` sorted by id |
| `POST` | `/api/admin/workers/{id}/load_model` | admin | Enqueues an arq job (`load_model_on_worker`) that proxies to the worker's `/load_model` and surfaces progress via the existing `/api/jobs/{job_id}/stream` SSE. Returns `JobResponse` so the frontend can attach to the SSE stream. |
| `POST` | `/api/admin/workers/{id}/evict_model` | admin | Synchronous proxy to worker's `/evict_model` (fast call, no job needed) |
| `POST` | `/api/admin/workers/{id}/restart` | admin | **Deferred to Phase 6.** v1 uses host-side `docker compose restart` |
| `GET` | `/api/admin/registry` | admin | Returns `{models: [{id, downloaded, is_active, loaded_on_workers, size_bytes}]}` — `downloaded` is the union of `available_modes` across all online workers' Redis state |

**Auth model**: `SONGMAKER_INTERNAL_TOKEN` shared between web and worker containers via env var. Worker sends `X-Internal-Token: <token>` header on register and on every scheduler→worker call. Web validates with `hmac.compare_digest` in a router-level dependency on `internal_api.py` so a future endpoint can't accidentally skip the check. Adequate for trusted internal docker network. Same trust level as the existing Redis password.

**Security documentation** (`docs/security.md`, in this same phase — promoted from Phase 6):
- Document the `SONGMAKER_INTERNAL_TOKEN` shared secret model and its rotation procedure
- Document the trust boundary: control-plane endpoints share a process with the public API; reverse proxy must not expose `/api/internal/*` to the internet (add an explicit nginx/caddy rule example)
- Document what a compromised worker can reach (PG via existing creds; Redis; the volume mount it has) and what it cannot (auth tables — workers should use the future `songmaker_worker` PG role, see Phase 5 deferral note in the original routing plan)
- Note that internal endpoints binding to a separate port is the next hardening step if internet exposure becomes a risk

**Tests**:
- `tests/test_internal_api.py` — registration upserts, missing token rejects (router-level), replay protection
- `tests/test_workers_queries.py` — identity CRUD
- `tests/test_redis_worker_state.py` — read joined state, TTL expiry, missing key returns `offline`
- `tests/test_admin_api.py` — list workers returns correct shape (PG + Redis joined), registry endpoint computes union correctly

**Phase 2 verification**: start web container + acestep-worker-0. Worker registers itself once. Heartbeat populates Redis. `curl /api/admin/workers` returns one row with `status: online`. Kill worker, wait 16 seconds, status flips to `offline` automatically (no cron needed).

---

### Phase 3 — Scheduler in music-worker (cutover)

**Goal**: route generation jobs to workers via the new scheduler. **Deletes** the existing `acestep_manager.py` and `mgr.switch_model` flow. This is the cutover phase — after this commit, the music-worker no longer talks to ACE-Step directly.

**New file**: `src/songmaker_cli/scheduler.py`

```python
class NoCapacityError(Exception): pass


def pick_worker(session: Session, target_model: str) -> WorkerInfo:
    # Joined view: PG identities + Redis ephemeral state, online workers only
    workers = list_online_workers(session)
    if not workers:
        raise NoCapacityError("No online ACE-Step workers")

    # Prefer a worker that already has the model loaded
    loaded = [w for w in workers if target_model in w.loaded_models]
    if loaded:
        return min(loaded, key=lambda w: w.queue_depth)

    # Otherwise least-busy worker (will need to load the model)
    return min(workers, key=lambda w: w.queue_depth)


async def dispatch_generation(session, request: GenerationRequest) -> GenerationResult:
    worker = pick_worker(session, request.model)

    # Atomic queue claim: INCR before dispatching so concurrent dispatches see the load
    # immediately, not after the next 5s heartbeat. Always DECR in `finally`.
    incr_queue_depth(worker.id)
    try:
        async with httpx.AsyncClient(timeout=30) as client:  # short timeout — these are fast calls
            if request.model not in worker.loaded_models:
                await client.post(
                    f"{worker.base_url}/load_model",
                    json={"mode": request.model},
                    headers=_internal_headers(),
                )

            resp = await client.post(
                f"{worker.base_url}/generate",
                json=request.to_worker_payload(),
                headers=_internal_headers(),
            )
            task_id = GenerateTaskResponse.model_validate(resp.json()).task_id

        # Subscribe to the worker's task SSE stream. Reconnects on transport error
        # without losing server-side progress — the task is alive on the worker.
        return await consume_task_stream(worker, task_id)
    finally:
        decr_queue_depth(worker.id)


async def consume_task_stream(worker: WorkerInfo, task_id: str) -> GenerationResult:
    """Subscribe to /tasks/{id}/stream via SSE. Reconnect on transport drop.
    Returns when the worker emits `done`. Raises on `error` event or after MAX_RECONNECTS."""
    reconnects = 0
    while True:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=None, write=10, pool=10)) as client:
                async with client.stream(
                    "GET",
                    f"{worker.base_url}/tasks/{task_id}/stream",
                    headers=_internal_headers(),
                ) as resp:
                    async for line in resp.aiter_lines():
                        event = parse_sse_line(line)
                        if event is None:
                            continue
                        if event.type == "done":
                            return GenerationResult.model_validate(event.data)
                        if event.type == "error":
                            raise WorkerTaskFailed(event.data["message"])
                        # `progress` events: optional logging / job-status update
        except (httpx.TransportError, httpx.RemoteProtocolError) as e:
            reconnects += 1
            if reconnects > MAX_SSE_RECONNECTS:  # 5
                raise
            await asyncio.sleep(min(2 ** reconnects, 30))
            # Loop reconnects to the same task_id; worker replays current state on connect.
```

**Why SSE, not polling**: SSE re-uses the existing pattern (`/api/jobs/{job_id}/stream`), pushes events immediately, and the worker's task store replays current state on reconnect — so a dropped connection mid-generation is recoverable. The worker keeps generating regardless of whether the scheduler is currently subscribed.

**Failure handling**:
- **SSE drops** → automatic reconnect to the same task_id, up to `MAX_SSE_RECONNECTS=5` with exponential backoff (capped at 30s).
- **Worker dies completely** (Redis key expires) → SSE reconnect fails with connection refused; arq retries the whole job; `pick_worker()` picks a different worker on retry.
- **Worker `error` event** → raised as `WorkerTaskFailed`, no retry (the model itself rejected the job).
- **Retry budget**: max 3 arq attempts per generation. Prevents infinite loop on a permanently broken model.

**Changes to existing files**:

| File | Change |
|---|---|
| `src/songmaker_cli/jobs.py` | `run_generation_job` calls `dispatch_generation()` instead of `mgr.switch_model + generate_single`. The hard "is downloaded" gate moves to the worker (it'll fail to load); the scheduler returns a clean error |
| `src/songmaker_cli/music_worker.py` | Delete `_setup_acestep_manager`, `reinitialize_acestep` job, `_publish_acestep_status`, `_publish_acestep_loading_status`. **No new cron** — Redis TTL handles stale-worker detection. |
| `src/songmaker_cli/acestep_manager.py` | **Delete entirely** |
| `src/songmaker_cli/generation_api.py` | `api_generate_song`, `api_repaint_generation`, `api_cover_generation`: validate at least one online worker exists; otherwise 503. Remove the `list_active_models` check (model identity check moves to the scheduler/worker) |
| `src/songmaker_cli/api_models/settings.py` | Remove `AceStepStatusResponse` (currently at line 188) — was incorrectly listed as `api_models/admin.py` in the original draft |
| `src/songmaker_cli/admin_api.py` | Delete `/acestep/status` and `/acestep/reinitialize` endpoints |
| `src/acestep_engine/` | **Unchanged.** Stays as the HTTP client to the ACE-Step subprocess inside a worker. The worker's `wrapper.py` uses it. |
| `docker-compose.yml` | Remove ACE-Step subprocess startup from `songmaker-music-worker`. Music-worker becomes smaller — no GPU access, no model weights mount, no acestep deps, no huggingface_hub. Strip those from `Dockerfile.worker`. Downloads run on the acestep-worker, not the music-worker. |
| `src/songmaker_cli/constants.py` | Remove `ACESTEP_*_REDIS_KEY`, `ACESTEP_PORT`, etc. (verify with grep — they're referenced in `acestep_manager.py`, `music_worker.py`, `admin_api.py`, `acestep_engine/client.py`) |

**Docs updated in this phase** (per cross-cutting rule 3):
- `docs/architecture.md` — replace the music-worker-owns-acestep diagram with the worker pool diagram from this plan
- The "ACE-Step Server" section in `docs/acestep.md` is updated to reflect the new scheduler dispatch path; deeper operator details (worker restart, metrics) stay deferred to Phase 6

**Tests**:
- `tests/test_scheduler.py` — `pick_worker` policies (prefer loaded, fall back to least busy, no workers raises). Mock DB + Redis. SSE reconnect on transport drop. Atomic INCR/DECR pairing under concurrency.
- `tests/test_jobs.py` — `run_generation_job` calls `dispatch_generation` correctly.
- `tests/test_music_worker.py` — Update for deleted manager (most assertions about acestep state-publishing get deleted).
- `tests/test_generation_api.py` — Validate "no workers online" returns 503.
- `tests/test_acestep_manager.py` — **Delete entirely.**

**Phase 3 verification**: end-to-end generation through the new path on the feature branch.

```bash
ruff check src/ tests/ acestep_worker/
pytest tests/ -n auto -q --cov=songmaker_cli --cov=acestep_worker --cov-report=term-missing
docker compose down
docker compose build
timeout 180 docker compose up -d --wait
docker compose ps  # all healthy

# Smoke test
curl /api/admin/workers  # one online worker
# In UI: generate a song. Job completes via the new scheduler path. Multiple variants work.
```

---

### Phase 4 — Admin UI rewrite (Worker Pool + Model Registry)

**Goal**: replace the current ACE-Step admin tab with two clean panels.

**Frontend changes** in `frontend/src/routes/settings/users/+page.svelte`:

The current ACE-Step tab section (lines 859-934 of the old version) is rewritten as **two stacked panels**.

#### Panel 1: Worker Pool

```
┌─ Worker Pool ─────────────────────────────────────────┐
│  ● acestep-worker-0     GPU 0  •  24 GB                │
│    Loaded:  xl-sft (12 GB)                             │
│    Status:  Idle                                       │
│    Queue:   0 jobs                                     │
│    Last seen: 2s ago                                   │
│    [Load model ▾] [Evict xl-sft] [Restart]            │
│                                                        │
│  (2nd card auto-appears when acestep-worker-1 added)   │
│                                                        │
│  ⚠ acestep-worker-1     GPU 1  •  Loading…             │
│    Target: xl-base                                     │
│    Started: 1m 23s ago                                 │
└────────────────────────────────────────────────────────┘
```

Per card:
- ID, GPU, VRAM total
- Currently loaded models (with size + load timestamp)
- `target_loading` if any (with elapsed time)
- Queue depth
- Last heartbeat
- Actions: Load model (dropdown of downloaded modes), Evict {model} (per loaded model), Restart

When `target_loading` is non-null, the card shows a spinner and the actions are disabled.

The "Pin" action is **stubbed** (button disabled with "Coming when multi-model-per-GPU is supported").

#### Panel 2: Model Registry

```
┌─ Model Registry ──────────────────────────────────────┐
│  ✓ sft       downloaded  available  loaded ×1   [⋮]   │
│  ✓ turbo     downloaded  available             [⋮]   │
│  ✓ xl-sft    downloaded  available  loaded ×1   [⋮]   │
│  ⚠ xl-turbo  downloaded  inactive              [⋮]   │
│  ✗ xl-base   not downloaded                    [Download]│
└────────────────────────────────────────────────────────┘
```

Per row:
- **downloaded** badge if any worker reports the mode in `available_modes`
- **available** badge if `is_active=true`
- **loaded ×N** count of workers currently holding it
- Toggle for `is_active` (gated: cannot enable a non-downloaded model)
- **Download** button if not downloaded — Phase 5

**Where the data comes from**:

`GET /api/admin/registry` returns:
```json
{
  "models": [
    {
      "id": "sft",
      "downloaded": true,
      "is_active": true,
      "loaded_on_workers": ["acestep-worker-0"],
      "size_bytes": 4823928320
    }
  ]
}
```

The web container can't directly check the filesystem (no checkpoints mount). Instead, **workers report `available_modes` in their heartbeat**. The control plane unions these across workers. Correct because workers share the same volume mount.

**Frontend API client** (`frontend/src/lib/api/admin.ts`):

```typescript
export async function listWorkers(): Promise<WorkerPoolResponse>
export async function loadModelOnWorker(workerId: string, mode: string): Promise<JobStatus>
export async function evictModelOnWorker(workerId: string, mode: string): Promise<void>
export async function restartWorker(workerId: string): Promise<void>
export async function getRegistry(): Promise<RegistryResponse>
```

The old `getAceStepStatus` and `reinitializeAceStep` are **removed**.

**Polling**: the worker pool panel auto-refreshes every 3 s (workers heartbeat every 5 s; 3 s polling keeps the UI snappy). Pause polling when the tab is hidden.

**Tests**:
- `frontend/src/lib/api/client.test.ts` — extend with new endpoints, mock responses
- Manual smoke tests in Verification

**Phase 4 verification**: full UI walkthrough. See the end-to-end manual test in **Verification**.

---

### Phase 5 — UI-driven downloads with progress

**Goal**: download button in the registry panel triggers a download on a specific worker; progress streams to the UI via the existing SSE infrastructure.

**The download lives on the acestep-worker, not the music-worker.** The worker is the natural owner: it has the volume mount, the huggingface_hub dependency, and the right trust scope. The music-worker stays GPU-free and acestep-free as Phase 3 promised.

**Worker-side**: `acestep_worker/downloads.py` (introduced in Phase 1 as a stub) gets the real implementation:

```python
# In acestep_worker/downloads.py
async def download_model(task_store: TaskStore, mode: str) -> str:
    """Returns task_id immediately. Runs the download in a background task."""
    config_path = MODEL_CONFIG_PATHS[mode]
    dest = ACESTEP_CHECKPOINT_DIR / config_path
    expected_size = ESTIMATED_MODEL_SIZE_BYTES[mode]

    task_id = task_store.create("download", {"mode": mode})

    async def _run():
        try:
            progress_poll = asyncio.create_task(_poll_dest_size(dest, expected_size, task_store, task_id))
            try:
                await asyncio.to_thread(
                    snapshot_download,
                    f"ACE-Step/{config_path}",
                    local_dir=str(dest),
                    token=os.environ["HF_TOKEN"],
                )
            finally:
                progress_poll.cancel()
            task_store.complete(task_id, {"mode": mode, "size_bytes": _dir_size(dest)})
        except Exception as e:
            task_store.fail(task_id, str(e))

    asyncio.create_task(_run())
    return task_id


def is_model_downloaded(mode: str) -> bool:
    """New helper. Filesystem check: are all expected shards present for `mode`?"""
    config_path = MODEL_CONFIG_PATHS.get(mode)
    if not config_path:
        return False
    dest = ACESTEP_CHECKPOINT_DIR / config_path
    return dest.exists() and _has_all_expected_shards(dest, mode)
```

The `POST /download_model` endpoint on the worker (introduced in Phase 1) calls `download_model()` and returns `{task_id}`. Progress streams via the same `/tasks/{task_id}/stream` SSE endpoint as generation tasks.

**huggingface_hub gotchas to handle**:
- xet token refresh bug → set `HF_HUB_DISABLE_XET=1` in the **acestep-worker** container env
- Network drops mid-download → huggingface_hub's resume from cache handles this
- Partial shards from a previous failed run → recoverable; `is_model_downloaded` does a strict "all expected shards present" check
- Retry policy: handled at the scheduler/admin layer, not inside the task itself — 3 attempts via the admin endpoint

**Web-side**: a new admin endpoint that proxies to the worker. The arq job pattern (used for `load_model` in Phase 2) is reused — the job handler picks a worker, calls `POST /download_model`, then SSE-subscribes to the task stream and forwards events to the existing `/api/jobs/{job_id}/stream`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/admin/registry/{mode}/download` | admin | Picks an online worker, enqueues a `download_model_on_worker` arq job, returns `JobResponse` |

The arq job (`download_model_on_worker` in `jobs.py`):
1. Pick any online worker (downloads do **not** call `incr_queue_depth` — they don't compete with generation for the queue slot, and don't need the prefer-loaded heuristic). Selection is just "first online worker" sorted by id for determinism.
2. `POST /download_model` to that worker → get task_id
3. SSE-subscribe to `/tasks/{task_id}/stream` and forward events to the arq job's progress channel (which is what `/api/jobs/{job_id}/stream` reads from)
4. On `done`, mark the arq job complete; on `error`, fail it

Frontend uses the existing `/api/jobs/{id}/stream` SSE endpoint — same client code as for generation jobs. The download row in the registry panel shows an inline progress bar.

**`scripts/download_models.sh`** stays as a CLI escape hatch — useful for fresh installs, CI, and bootstrapping when no worker is yet running.

**Tests**:
- `tests/acestep_worker/test_downloads.py` — extend with full implementation: success path, retry on failure, idempotent skip if already downloaded, partial download recovery, progress events on the task stream, `is_model_downloaded` shard check
- `tests/test_jobs.py` — `download_model_on_worker` arq job: picks a worker, forwards SSE events, fails on worker error
- `tests/test_admin_api.py` — `POST /api/admin/registry/{mode}/download` enqueues job, validates mode, rejects unknown modes, rejects when no workers online

**Phase 5 verification**: download a model from the UI end-to-end. Progress bar updates. On completion, registry row updates to "downloaded" (the worker's next heartbeat publishes the new `available_modes`).

---

### Phase 6 — Polish + observability + cleanup

Everything that's "make it production-ready" but not blocking for the cutover.

> **Revised after Phases 1–5 shipped.** Several originally-listed items either landed earlier (concurrent same-mode downloads in Phase 5, multi-model-routing.md superseded marker) or have a different starting state than the original draft assumed. New items collected from Phase 4 / Phase 5 deferrals are appended below the original list.

**Items** (in priority order):

1. **Worker metrics in the existing Prometheus endpoint**. The `/metrics` endpoint already exists in [health_api.py:117](../src/songmaker_cli/health_api.py#L117) with HTTP, jobs_by_type, queue_depth, GPU VRAM, active_sessions. **Extend it** with worker pool metrics (don't build a new endpoint):
   - `songmaker_acestep_workers_total{status="online|loading|offline"}` (gauge)
   - `songmaker_acestep_worker_loaded_models{worker_id="..."}` (gauge per loaded model count)
   - `songmaker_acestep_worker_queue_depth{worker_id="..."}` (gauge — read from Redis)
   - `songmaker_acestep_model_load_duration_seconds{mode="..."}` (histogram)
   - `songmaker_acestep_generation_duration_seconds{mode="..."}` (histogram)
   - `songmaker_acestep_download_duration_seconds{mode="..."}` (histogram, added with Phase 5 — measure end-to-end download time for capacity planning)

   **Note:** `acestep_workers_total` and `acestep_workers_online` are already exposed via `/health` (added in Phase 3 cutover, [health_api.py:220-221](../src/songmaker_cli/health_api.py#L220-L221)). Phase 6's job is to mirror them into Prometheus format under `/metrics` and add the per-mode histograms. The existing Grafana board can be updated to show worker pool capacity and per-model latency.

2. **Admin restart endpoint via the worker** (deferred from Phase 2 + Phase 4 admin UI). Adds `POST /api/internal/restart` to the worker, called by `/api/admin/workers/{id}/restart`. The worker calls `os.kill(os.getpid(), signal.SIGTERM)` and exits; docker healthcheck restarts the container. Phase 4 explicitly omitted the Restart button from the Worker Pool card pending this endpoint — wire it back into [WorkerPoolPanel.svelte](../frontend/src/lib/components/WorkerPoolPanel.svelte) when the endpoint ships.

3. **`pin_model` LRU exemption + admin UI button**. Wire the cache to skip pinned models in eviction. Pure no-op until LRU > 1, but having the API there means the admin UI button isn't a stub anymore. Phase 4 explicitly omitted the Pin button — wire it back into [WorkerPoolPanel.svelte](../frontend/src/lib/components/WorkerPoolPanel.svelte) at the same time.

4. **Worker startup failure surfacing — partially shipped, needs finishing.** [registry_client.py:13](../src/acestep_worker/registry_client.py#L13) already does bounded retry: `DEFAULT_RETRY_DELAYS_SECONDS = (1.0, 2.0, 5.0, 10.0, 30.0)` — 5 attempts (~48 s total) with backoff, then raises `RegistrationFailedError` and the worker dies. The original Phase 6 framing said *"today it just logs and dies"*; reality is closer to *"it retries 5 times then logs and dies."* Phase 6 still needs:
   - **Indefinite retry with cap-and-jitter backoff** instead of the current bounded list (e.g., 1s → 2s → 5s → 10s → 30s → 60s → 60s … forever). Operators should not have to babysit worker startup ordering.
   - **Healthcheck integration** — the docker healthcheck on `acestep-worker-0` should report unhealthy until the worker has successfully registered with the control plane, so `docker compose up --wait` waits for the registration round-trip rather than just the FastAPI server's `/health`.
   - **Container log surfacing** — the existing log line is good; add a brief startup banner ("waiting for control plane at $CONTROL_PLANE_URL") so the operator can spot the failure immediately.

5. **Concurrent in-flight generation handling — describe the actual race.** Original Phase 6 wording said *"the worker refuses the load (lock held by the generation)"*. **That's wrong.** Verified by reading [model_cache.py:92-112](../src/acestep_worker/model_cache.py#L92-L112) and [wrapper.py:124-143](../src/acestep_worker/wrapper.py#L124-L143):
   - Generations are **lock-free** at the cache layer. `/generate` calls `cache.get_loaded(mode)` (no lock), then spawns the generation as a background task via `spawn_background`.
   - The cache `asyncio.Lock` is only held by `cache.load()` and `cache.evict()`, NOT by in-flight generations.
   - **The actual race:** an admin `POST /load_model` for a *different* mode acquires the lock, calls `_evict_to_fit(target_size)`, and can evict the model that the in-flight generation is currently using → generation crashes with a stale model handle.

   **Fix options for Phase 6:**
   - **(a)** Track in-use models via a per-mode reference count (`{mode: usage_count}` in the cache). `evict()` and `_evict_to_fit()` skip modes with `usage_count > 0`. The generation runner increments on start and decrements on completion. Cleanest, but requires touching the lock-free read path.
   - **(b)** Refuse `/load_model` (return 409) if any in-flight generation is using a model that would need eviction to make room. Conservative.
   - **(c)** Queue the `/load_model` to run after the current generation drains (the SSE task pattern naturally supports this). Best UX, most code.

   Recommend **(a)** with **(b)** as the test fallback. Document the trade-off in the operator docs (item 6).

6. **Operator documentation rewrite.** A short download-flow paragraph was added in Phase 5 (`e36fd4e`, [docs/acestep.md](../docs/acestep.md)). Phase 6's full rewrite still needs:
   - Worker restart procedure (depends on item 2)
   - Prometheus metric keys + Grafana panel descriptions (depends on item 1)
   - Troubleshooting playbooks: "worker won't register", "download stalls", "load fails on full GPU", "stale-job reaper killed my generation"
   - Operator-facing reference for the Redis key namespace (`songmaker:acestep:worker:*`, `songmaker:acestep:queue:*`, `songmaker:acestep:download:*`) and what each key means

   **No rewrite needed for** `docs/architecture.md` (updated in Phase 3 cutover) or `docs/security.md` (updated in Phase 2 when the internal token landed).

7. ~~**Mark `plans/multi-model-routing.md` as SUPERSEDED.**~~ **DONE** before Phase 1 — the file header already has `STATUS: SUPERSEDED → plans/acestep-worker-pool.md` with rationale. Strike from the Phase 6 list.

8. **Memory update** — write a memory: "Always check `plans/` folder before drafting plans — the project has multi-phase plan files in there, and new plans should either supersede or extend existing ones, never silently overlap."

#### New items collected from Phase 4 / Phase 5 deferrals

**(a) Per-loaded-model VRAM size in the Worker Pool admin UI.** Phase 4 sub-plan D2 deferred this: *"VRAM size per model is not in the response — the parent plan's '(12 GB)' annotations are aspirational."* Implementation: extend the worker heartbeat payload's `loaded` field from `list[str]` to `list[{mode: str, size_gb: float}]`. This is a heartbeat schema change, so the contract test [test_acestep_state.py::test_heartbeat_payload_keys_match_admin_reader](../tests/test_acestep_state.py) (added in `c5a11e0`) must be extended in the same PR. The control plane reader and frontend display update follow mechanically.

**(b) "Loading X… (1m 23s elapsed)" counter on Worker Pool cards.** Phase 4 sub-plan D2 deferred this: *"the Redis state doesn't carry a `loading_started_at` field. Decision: just say 'Loading {target_loading}…' without an elapsed counter."* Implementation: add `loading_started_at: str | None` to the heartbeat payload. Same heartbeat-schema-change rule applies — extend the contract test in the same PR. Frontend [WorkerPoolPanel.svelte::describeStatus](../frontend/src/lib/components/WorkerPoolPanel.svelte) computes the elapsed time client-side from the timestamp.

**(c) Download auto-retry policy (3 attempts).** Phase 5 sub-plan D14 deferred this: *"Auto-retry is NOT in Phase 5. The parent plan mentions '3 attempts via the admin endpoint' — that's deferred to Phase 6."* Implementation: wrap the SSE consumption + worker POST in `download_model_on_worker` ([jobs.py](../src/songmaker_cli/jobs.py)) in a retry loop. After 3 attempts the job fails with `error_type=download_error`. Be careful not to leak the Redis flag between retries — the existing `try/finally` already handles this since `clear_download_in_progress` runs at the end of every attempt.

#### Items already done that were originally Phase 6 candidates

These shipped in earlier phases and are NOT Phase 6 work:

- **Concurrent same-mode downloads** — solved in Phase 5 via Redis flag with atomic SET-NX (`a0e5136` + the user-applied tightening to `set_download_in_progress` using `nx=True`). The Phase 5 sub-plan originally deferred this; Phase 5 review pushed back and it shipped in Phase 5.
- **Heartbeat field-name writer/reader contract** — fixed in `cf1fa5d`, pinned by the regression test added in `c5a11e0`. Phase 6 metrics work and items (a)/(b) above must respect this contract test.
- **Atomic ModelCache state snapshot** — fixed in `c32b246`. The race was discovered during Phase 3 smoke test and fixed inline.
- **`is_model_downloaded` shard-aware layout detection** — fixed in `b5a984d`. The Phase 5 download flow relies on this as the source of truth.

#### Phase 6 PR split

The original "Phase 6 can be split into 2 PRs (observability + everything else)" is still the right call. Suggested split:

- **PR 1 — Observability:** items 1, 4 (registration retry/healthcheck), 6 (operator docs metric keys section)
- **PR 2 — UX + correctness:** items 2 (restart), 3 (pin), 5 (load-while-generating race fix), 6 (operator docs troubleshooting), (a), (b), (c)

PR 2 is bigger and depends on more cross-cutting changes; ship PR 1 first to get production observability while PR 2 is in review.

---

### Phase 7 — Cross-cutting cleanup sweep

**Goal:** one final pass to catch cross-cutting stale references that no single phase's self-review is positioned to find — `CLAUDE.md` debt entries, `docs/` consistency across the Phase 3 + Phase 6 writes, frontend grep after Phase 4 rewrites the admin tab, stale env files, repo-wide dead symbol sweep. **Deletions and doc updates only, no new features.**

**Why a dedicated phase and not a sub-step of Phase 6:** each phase's own self-review catches the dead code *that phase* creates. Cross-cutting cleanup benefits from a single pass at the end when everything is in its final state. Rolling it into Phase 6 would conflate polish-feature work with cleanup; keeping it as Phase 7 makes the cleanup commit reviewable on its own.

**Sub-plan:** [plans/acestep-worker-pool-phase7-subplan.md](acestep-worker-pool-phase7-subplan.md) — 11-step procedure with concrete grep commands, over-cleaning watch list, and verification checklist. Read it before starting.

**Size:** 1–2 hours. One commit.

**Run when:** after Phases 1–6 are all committed and the full test suite is green at the Phase 6 commit. Not earlier.

---

### Phase 8 — Image architecture refactor (bake the inner ACE-Step venv, narrow the bind mount)

> **Section revised after Phases 1–7 shipped and after the Phase 6 PR 2 smoke test re-hit the bug.** The original framing in this section talked about a 3-base-image hierarchy and "the music-worker re-downloads multi-GB wheels". Both were imprecise. The actual problem is much narrower (the inner ACE-Step subprocess only) and the fix can be much smaller than a full image-architecture refactor. This section now distinguishes the **minimum viable fix** from the **optional bigger cleanup**, and locks down what the sub-plan must answer.

**Goal:** stop the inner ACE-Step subprocess from doing a 5–15 minute `uv sync` on every fresh container start. This is the venv-clobbering anti-pattern documented in `CLAUDE.md` technical debt, and it's the only reason the current smoke test cycle requires `ARQ_JOB_TIMEOUT=1800` as a workaround.

**Why a dedicated phase:** the fix touches Docker image build order, the bind mount layout in `docker-compose.yml`, and possibly `acestep_worker/subprocess_runner.py`. Bundling it into Phase 7 would inflate the cleanup sweep beyond "deletions and doc updates" and break its reviewable property. The pain only became visible after the Phase 3 cutover (and was re-confirmed during the Phase 6 PR 2 smoke test on `2026-04-07`).

#### What's actually broken (verified mechanism)

The current state of the system, as of commit `90f4c14`:

1. **The acestep-worker container's `/app/.venv`** (the wrapper FastAPI server's venv) **is correctly baked into the image**. [`docker/acestep-worker.Dockerfile`](../docker/acestep-worker.Dockerfile) does `uv sync --frozen --no-dev --extra acestep-worker` during the image build. The wrapper starts fast.

2. **The inner ACE-Step subprocess uses a SEPARATE venv** at `/app/_models/acestep/.venv`. This is because [`acestep_worker/subprocess_runner.py:start_acestep_subprocess`](../src/acestep_worker/subprocess_runner.py) invokes `uv run acestep-api` with `cwd=checkpoint_dir` (which resolves to `/app/_models/acestep`). uv looks for a `pyproject.toml` and `.venv` in the cwd, finds the upstream ACE-Step project's `pyproject.toml`, and uses/creates `/app/_models/acestep/.venv` based on that.

3. **`/app/_models/acestep/` is a bind mount** from the host's `./_models/acestep/` ([`docker-compose.yml:144`](../docker-compose.yml#L144)). The host venv was created by Felix's local development against the host's Python (3.13 or whatever) and contains a Python interpreter symlink. The container's Python is 3.12 in `/usr/local/bin/python3.12`. uv detects the symlink mismatch, considers the venv broken, deletes it, and recreates it from scratch by downloading every dependency:
   - `torch`, `torchvision`, `torchaudio`, `torchcodec`, `torchao`
   - `nvidia-cublas-cu12` (566 MB), `nvidia-cudnn-cu12` (674 MB), `nvidia-cusparselt-cu12` (274 MB)
   - `triton` (179 MB), `transformers`, `diffusers`, `tokenizers`
   - `gradio`, `tensorboard`, `matplotlib`, `pandas`, `numpy`, `numba`, `llvmlite`
   - plus dozens more
   
   Total: ~3-4 GB of wheels. Wall-clock time on a fast connection: 5-15 minutes. On a slow connection: longer than the `ARQ_JOB_TIMEOUT=1800` (30 minute) override.

4. **The pain only affects fresh container starts** (first `/load_model` after `docker compose up --force-recreate` or after the host's `_models/acestep/.venv` is wiped). Once the venv is re-populated in the bind mount, subsequent loads are fast. But `--force-recreate` is needed every time we deploy a new image, so this hits us on every backend release.

5. **The music-worker is NOT affected.** Since the Phase 3 cutover, music-worker doesn't touch ACE-Step at all — its image is already minimal. **Earlier drafts of this section incorrectly mentioned the music-worker; that's outdated.** The bind-mount problem is scoped entirely to `acestep-worker-0`.

#### Fix options (the sub-plan must pick one and justify)

There are three viable fixes, in increasing order of scope. The sub-plan should evaluate all three, pick one, and document the rejected alternatives with rationale. The minimum viable fix is **(A)**.

**Option A — Single shared venv (smallest change, recommended starting point).**

Stop using a separate venv for the inner ACE-Step subprocess. Instead, install the ACE-Step deps INTO `/app/.venv` (the wrapper's venv) during the image build, and change `subprocess_runner.start_acestep_subprocess` to invoke the inner subprocess against that venv directly — either by:
- Calling `/app/.venv/bin/python -m acestep_api ...` instead of `uv run acestep-api ...`
- Or invoking `uv run` with `--directory /app` so uv finds `/app/pyproject.toml` and `/app/.venv` instead of the bind-mounted ones
- Or setting `VIRTUAL_ENV=/app/.venv` in the subprocess env

**Pros:** smallest diff. No new Dockerfile, no compose change beyond optionally narrowing the bind mount. Single venv per container is the simplest mental model.

**Cons:** the wrapper's `--extra acestep-worker` extra in `pyproject.toml` would need to grow significantly to include all of ACE-Step's deps (torch + diffusers + transformers + ...). The current extra is intentionally minimal (`fastapi`, `uvicorn`, `redis[hiredis]`, `huggingface_hub`). Verify the dep set merges cleanly without conflicts. Image size grows from ~500 MB to ~6-8 GB.

**Open questions for the sub-plan:**
- Does the upstream ACE-Step `pyproject.toml` declare its deps cleanly, or does it rely on `uv sync` resolving against its own `uv.lock`?
- Are there any version conflicts between `acestep_worker`'s current deps (`fastapi`, `redis[hiredis]`) and ACE-Step's (e.g., a different `pydantic` major)?
- Does the wrapper need any of ACE-Step's deps at import time, or is the subprocess truly independent?

**Option B — Two venvs, both baked into the image, narrow the bind mount.**

Keep the separate inner-ACE-Step venv at `/app/_models/acestep/.venv`, but bake it into the image during build (run `uv sync` against the upstream `pyproject.toml` as a Dockerfile RUN step). Then narrow the docker-compose bind mount from `./_models/acestep:/app/_models/acestep` to `./_models/acestep/checkpoints:/app/_models/acestep/checkpoints` so the host's broken `.venv` doesn't shadow the baked one.

**Pros:** the two venvs stay isolated. No risk of dep conflicts between wrapper and ACE-Step. The wrapper image stays small (and the ACE-Step deps form their own layer that can be cached independently).

**Cons:** the Dockerfile gets a second `uv sync` step that's slower and harder to cache (the upstream ACE-Step `pyproject.toml` lives inside `_models/acestep/` which is a git-untracked submodule-like directory — the build context needs to include it). The bind mount narrowing requires verifying nothing else in `_models/acestep/` is needed at runtime besides `checkpoints/` (e.g., the upstream `acestep/` source code).

**Open questions for the sub-plan:**
- What's actually inside `_models/acestep/` besides `.venv` and `checkpoints/`? (Likely the upstream ACE-Step source — `acestep/`, `setup.py`, etc.)
- Does the inner subprocess import any Python modules from `_models/acestep/acestep/` at runtime, or only from its venv?
- If the subprocess needs the upstream source at runtime, can we COPY it into the image at a different path (`/opt/acestep/`) and run from there?

**Option C — Full base-image hierarchy refactor (the original plan).**

Introduce three reusable base images:
```
                    python:3.12-slim
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
   acestep-base     scoring-base      app-base
   (~6-8 GB)        (~4-6 GB)         (~500 MB)
   torch + cudnn    torch + whisper   fastapi + arq
   diffusers        + audiobox        + sqlalchemy
   ACE-Step venv    + HF weights      + audio_engine
         │                │                │
         ▼                ▼                ▼
   acestep-worker   scoring-worker    music-worker
   (~80 MB layer)   (~30 MB layer)    (~20 MB layer)
                                          │
                                          ▼
                                    songmaker-web
                                    (~100 MB layer)
```

Splits `Dockerfile.worker` into per-service images, deduplicates the torch layer between scoring and acestep, and gives each leaf image a fast rebuild path because the heavy base layers stay cached.

**Pros:** structurally cleaner. Cuts cumulative build time across all services. Sets up the image hierarchy for any future GPU worker that needs torch (e.g., a separate audiobox-only worker). Eliminates the historical baggage of `Dockerfile.worker` being shared between music-worker and scoring-worker (Phase 7 D1 supersession).

**Cons:** much bigger refactor. Touches all four services. Requires a base-image build step in CI (or a `docker build` chain). Image registry decisions (local-only vs push to GHCR). Versioning scheme for the base images (content hash vs semver). One-time full rebuild of everything for the migration.

**Recommendation:** **start with Option A or B for the minimum viable fix in this PR**, and treat Option C as a separate follow-up after we've validated the minimal fix works in production for a few days. Option C is real value but it's not on the critical path to unblocking the smoke test.

The sub-plan can pick the recommended path with a one-paragraph rationale and either keep Option C as a "future" item or fold it into Phase 8 if it's small enough on top of A/B. **The user explicitly does not want a 1-day refactor to unblock a 1-hour smoke test.**

#### Decisions the sub-plan must lock in

1. **Which fix option (A, B, or C)** — locked, with rationale for why the others were rejected
2. **Whether `_models/acestep/checkpoints/` stays a bind mount.** It must — the model weights are 3-13 GB per model and survive container rebuilds. Confirm that narrowing the mount path to just `checkpoints/` doesn't break anything else
3. **What lives inside `_models/acestep/` besides `checkpoints/` and `.venv`.** Audit the directory and document each subdirectory. Decide which need to move into the image and which can stay on the host (or be deleted)
4. **The exact `subprocess_runner.start_acestep_subprocess` invocation** after the fix. Concrete `cmd` list and `env` dict. The 300s/1800s startup timeout becomes irrelevant after this — actual subprocess startup is ~30s once the venv exists
5. **Backward compatibility for developers running locally** without docker. Some developers may have a working host venv that they want to keep. The fix should not break their workflow — at most, document the new convention
6. **`ARQ_JOB_TIMEOUT` rollback.** After the fix, the `.env:26` `ARQ_JOB_TIMEOUT=1800` workaround becomes unnecessary. The sub-plan should explicitly drop it back to the documented default (`300` per `.env.docker.example:43`) in the same commit
7. **Smoke test procedure.** End-to-end: `docker compose down -v && docker compose up -d --build --wait songmaker-acestep-worker-0 && time docker compose exec songmaker-acestep-worker-0 curl -X POST -H 'Content-Type: application/json' -d '{"mode":"sft"}' http://localhost:8001/load_model`. Expected: <90 seconds end-to-end
8. **Rollback plan.** If the new image has a startup regression, what's the recovery path? (Probably: revert the commit, rebuild, restart.)

#### What's NOT in scope for Phase 8

- ACE-Step model weight downloads (Phase 5 territory — already shipped)
- Multi-host worker deployment (out of scope for the current single-node architecture)
- GPU isolation between workers (single-GPU assumption stays)
- CI/CD changes for image registry pushes (only do this if Option C is picked AND the user explicitly wants it)
- New runtime features

#### Sub-plan deliverable

`plans/acestep-worker-pool-phase8-subplan.md`, same depth as Phase 3/4/5/6 sub-plans. Should include:

- State at start (commit SHA, what's already in place)
- The "What's actually broken" verified mechanism (cribbed from this section, expanded with line numbers)
- Decision matrix: A vs B vs C with explicit rationale
- Concrete Dockerfile diff (full file listing for the chosen option)
- Concrete `docker-compose.yml` diff
- Concrete `subprocess_runner.py` diff (if the chosen option touches it)
- Concrete `pyproject.toml` diff (if the chosen option touches extras)
- Files Touched table
- Implementation order with HARD checkpoints (`docker compose build` after each major step)
- Smoke test plan (the end-to-end load test)
- Watchpoints (e.g., dep conflicts surfaced during `uv sync`, the cwd change in subprocess_runner, the `ARQ_JOB_TIMEOUT` rollback)
- Rollback plan
- Quick context for the next session

**Size estimate:** sub-plan write-up ~1-2 hours; implementation depends on chosen option. Option A: ~2-3 hours (mostly waiting for `docker compose build`). Option B: ~3-4 hours. Option C: ~1 day.

**Run when:** after Phase 7 ships (`90f4c14`). Phases 1–7 are now stable on `feat/acestep-worker-pool` and the only remaining smoke test blocker is this venv-clobbering issue.

**Supersedes:** Phase 7 D1 ("split Dockerfile.worker") — that work is folded into Phase 8 if Option C is picked, or deferred indefinitely if Option A/B is picked (it's nice-to-have, not a blocker).

**Discovered + re-confirmed during:** Phase 3 smoke test (initial discovery), Phase 6 PR 2 smoke test on `2026-04-07` (re-confirmed; the inner subprocess uv sync was observed downloading nvidia-cublas-cu12, nvidia-cudnn-cu12, etc. before timing out at 300s).

---

## Files Touched (consolidated)

| File | Phase | Change |
|---|---|---|
| `pyproject.toml` | 1 | Register `acestep_worker` as a top-level package (peer of `acestep_engine`, `audio_engine`, `songmaker_cli`) |
| `acestep_worker/__init__.py` | 1 | New |
| `acestep_worker/wrapper.py` | 1 | New: FastAPI app with worker endpoints (incl. async `/generate`, `/tasks/{id}/stream`, `/download_model`) |
| `acestep_worker/model_cache.py` | 1 | New: LRU cache + subprocess management |
| `acestep_worker/task_store.py` | 1 | New: in-memory async task store with SSE replay-on-reconnect semantics |
| `acestep_worker/heartbeat.py` | 1 | New: 5s loop writing ephemeral state to Redis with 15s TTL |
| `acestep_worker/registry_client.py` | 1 | New: one-shot registration with control plane on startup |
| `acestep_worker/downloads.py` | 1, 5 | New: stub in Phase 1, full implementation in Phase 5; includes `is_model_downloaded` |
| `acestep_worker/models.py` | 1 | New: Pydantic models for worker API |
| `acestep_worker/__main__.py` | 1 | New: entry point |
| `docker/acestep-worker.Dockerfile` | 1 | New: image build (ACE-Step deps + huggingface_hub + the wrapper) |
| `docker-compose.yml` | 1, 3 | Add `songmaker-acestep-worker-0` (Phase 1); remove ACE-Step from music-worker (Phase 3); add `HF_HUB_DISABLE_XET=1` and `HF_TOKEN` to acestep-worker env |
| `tests/acestep_worker/test_wrapper.py` | 1 | New |
| `tests/acestep_worker/test_model_cache.py` | 1 | New |
| `tests/acestep_worker/test_task_store.py` | 1 | New |
| `tests/acestep_worker/test_heartbeat.py` | 1 | New |
| `tests/acestep_worker/test_registry_client.py` | 1 | New |
| `tests/acestep_worker/test_downloads.py` | 1, 5 | New: stub tests in Phase 1, full coverage in Phase 5 |
| `src/songmaker_cli/db/migrations/versions/<new>_acestep_workers.py` | 2 | New: alembic migration (identity-only schema, no ephemeral columns) |
| `src/songmaker_cli/db/models.py` | 2 | Add `AceStepWorker` SQLAlchemy ORM model |
| `src/songmaker_cli/db/queries/workers.py` | 2 | New: identity CRUD only (`register_worker`, `list_worker_identities`, `get_worker_identity`) |
| `src/songmaker_cli/db/queries/__init__.py` | 2 | Re-export the new query functions |
| `src/songmaker_cli/redis_keys.py` | 2 | New: helpers for `songmaker:acestep:worker:{id}` and `songmaker:acestep:queue:{id}` (or extend `redis_client.py`) |
| `src/songmaker_cli/api_models/workers.py` | 2 | New: `WorkerRegisterRequest`, `WorkerIdentity`, `WorkerEphemeralState`, `WorkerInfo`, `WorkerResponse`, `WorkerPoolResponse`, `RegistryModelResponse`, `RegistryResponse`, `GenerateTaskResponse`, `WorkerTaskEvent` |
| `src/songmaker_cli/internal_api.py` | 2 | New: `/api/internal/workers/register` with router-level shared-secret auth dependency |
| `src/songmaker_cli/admin_api.py` | 2, 4, 5 | Add `/api/admin/workers`, `/api/admin/registry`, `/api/admin/registry/{mode}/download`; remove `acestep_status` and `reinitialize_acestep` (Phase 3) |
| `src/songmaker_cli/server.py` | 2 | Mount `internal_api` router |
| `src/songmaker_cli/scheduler.py` | 3 | New: stateless picker + atomic queue claim + SSE task consumer with reconnect |
| `src/songmaker_cli/jobs.py` | 3, 5 | `run_generation_job` uses scheduler; new `load_model_on_worker` (Phase 2) and `download_model_on_worker` (Phase 5) arq jobs that proxy to worker SSE and forward events to the existing job-stream |
| `src/songmaker_cli/music_worker.py` | 3 | Delete acestep manager hooks. **No new cron** (Redis TTL handles staleness). |
| `src/songmaker_cli/acestep_manager.py` | 3 | **Delete** |
| `src/songmaker_cli/generation_api.py` | 3 | Validate "any online worker" instead of acestep status; remove old reinitialize/status endpoints |
| `src/acestep_engine/` | — | **Unchanged** |
| `src/songmaker_cli/api_models/settings.py` | 3 | Remove `AceStepStatusResponse` (currently at line 188). **Note**: original draft incorrectly listed this as `api_models/admin.py`, which does not exist. |
| `src/songmaker_cli/constants.py` | 3 | Remove `ACESTEP_*_REDIS_KEY`, `ACESTEP_PORT` (verify with grep — referenced in `acestep_manager.py`, `music_worker.py`, `admin_api.py`, `acestep_engine/client.py`) |
| `tests/test_scheduler.py` | 3 | New: pick policies, atomic queue increment, SSE reconnect on transport drop |
| `tests/test_jobs.py` | 3, 5 | Update for scheduler path; add `load_model_on_worker` and `download_model_on_worker` job tests |
| `tests/test_music_worker.py` | 3 | Update for deleted manager |
| `tests/test_generation_api.py` | 3 | Add "no online workers → 503" assertion |
| `tests/test_acestep_manager.py` | 3 | **Delete** |
| `tests/test_internal_api.py` | 2 | New |
| `tests/test_workers_queries.py` | 2 | New (identity CRUD) |
| `tests/test_redis_worker_state.py` | 2 | New (TTL expiry, missing-key handling) |
| `tests/test_admin_api.py` | 2, 4, 5 | Workers endpoints, registry endpoint, download endpoint |
| `frontend/src/lib/api/admin.ts` | 4 | Add worker pool + registry API; remove old ACE-Step status |
| `frontend/src/lib/api/types.ts` | 4 | Regenerated |
| `frontend/src/lib/api/client.test.ts` | 4 | Update mocks |
| `frontend/src/routes/settings/users/+page.svelte` | 4 | Rewrite ACE-Step tab as two panels |
| `src/songmaker_cli/health_api.py` | 6 | **Extend** existing `/metrics` with worker metrics (do not create new endpoint) |
| `monitoring/prometheus.yml` | 6 | No change needed (already scrapes the web container) |
| `docs/acestep.md` | 6 | Operator-facing rewrite (deeper detail than Phase 3 cutover doc update) |
| `docs/architecture.md` | **3** | Replace music-worker-owns-acestep diagram with worker pool diagram (in the same phase as the cutover) |
| `docs/security.md` | **2** | Document shared-secret auth model + control-plane trust boundary (in the same phase as the token is introduced) |
| `plans/multi-model-routing.md` | 6 | Verify `STATUS: SUPERSEDED → plans/acestep-worker-pool.md` (already done at top of file) |
| `plans/acestep-worker-pool.md` | (this file) | This plan |
| `scripts/generate_types.py` | (run) | Phases 2, 3, 4, 5 |

## Things I considered and decided against

- **Heartbeats via HTTP POST to the web container** (original draft): rejected after revision. Direct Redis writes are simpler, faster, and avoid making the web container's request handlers do bookkeeping work on every heartbeat. The web container reads Redis on demand for the admin UI; that's the only place it needs to know about ephemeral state.
- **PostgreSQL for ephemeral worker state**: rejected after revision. Writing to PG every 5s for state that's already volatile is the wrong primitive. Redis with TTL is exactly the right shape for "this worker exists right now". PG keeps the stable identity row.
- **Long-lived synchronous HTTP for `/generate`** (original draft, 600s timeout): rejected after revision. A 5-10 minute synchronous HTTP call is fragile across any proxy hop or network blip and discards the work on disconnect. The async-task + SSE pattern keeps server-side state alive across reconnects.
- **Polling instead of SSE**: SSE reuses existing infrastructure (`/api/jobs/{job_id}/stream`) and is push-based — events arrive immediately. Polling would also work but adds latency and request volume. SSE is the right choice given the existing plumbing.
- **Stale-worker reaper cron** (original draft): rejected after revision. Redis TTL handles expiry automatically. No cron needed. Less code, fewer failure modes.
- **gRPC instead of HTTP for the worker API**: overkill, all internal, no perf bottleneck.
- **Kubernetes-style operator pattern**: massive overkill for single-node. The architecture is k8s-compatible if you ever migrate.
- **Replace arq with the scheduler**: arq gives persistence, retries, dead-letter — wheels we shouldn't reinvent. Keep arq, scheduler runs inside the arq job handler.
- **Stateless worker with cache in scheduler**: GPU lives in the worker, cache must too.
- **Eviction policies other than LRU**: LFU and TTL make sense in some contexts; LRU + admin pin covers 99% of cases simply.
- **Multi-tenancy / job priorities**: not needed yet. "Least queue depth" is uniform priority.
- **Per-model arq queues** (the existing routing plan): rejected — see comparison table above. The first-class worker model is cleaner and unblocks the UX rewrite.
- **Downloads in the music-worker** (original draft): rejected after revision. Contradicts Phase 3's "music-worker has no model weights mount, no acestep deps". The acestep-worker is the natural owner.

## Open questions to resolve during implementation

1. **Estimated VRAM per model**: need accurate values for the LRU `_sizes` dict. Will measure during Phase 1 by loading each model and reading `nvidia-smi`. Stored in a constant in `acestep_worker/model_cache.py`.
2. **Subprocess vs in-process model loading, especially when LRU > 1**: today ACE-Step runs as a subprocess and the wrapper keeps that pattern (one subprocess per loaded model; LRU evict = SIGKILL). **Default for v1 (LRU=1): stay with subprocess** for crash isolation. **When LRU > 1 lands** (multi-model on a larger GPU), revisit: N subprocesses each holding ~12 GB plus a Python interpreter is wasteful, and ACE-Step's loader may support multiple models in one process. **Action in Phase 1**: measure subprocess memory overhead (RSS minus model size) so the answer is data-backed when it matters. Don't decide now; document the measurement.
3. **Worker → control plane auth in production**: shared secret env var is the v1 answer. mTLS or service mesh is a future hardening item if you go multi-node. Documented in `docs/security.md` in **Phase 2** (promoted from Phase 6).
4. **What happens to a generation in flight when its worker dies**: scheduler dispatches, worker dies mid-generation. With the SSE task pattern: SSE stream first reconnects up to 5 times (worker may restart and replay state). If reconnect budget exhausts, the arq job fails and retries; on retry, `pick_worker()` picks a different online worker. **Retry budget: 3 arq attempts per job** + 5 SSE reconnects per attempt.
5. **`docker compose restart` from inside a container**: avoided entirely. Workers self-restart via SIGTERM + healthcheck. Phase 6.
6. **Loading state during long load**: the worker's `target_loading` field is set in its in-memory state during the load; the 5s heartbeat publishes it to Redis under `songmaker:acestep:worker:{id}`. The admin UI polls `/api/admin/workers` (which reads PG identity + Redis state) and shows the spinner. **No PG row update during loading** — Redis is the source of truth for ephemeral state.
7. **Race conditions on `incr_queue_depth`**: Redis `INCR` is atomic. The `finally` block always `DECR`s, even on exception. The remaining edge case: if the scheduler process itself crashes between INCR and DECR, the counter leaks. **Mitigation**: on worker startup, the worker `DEL`s its own `queue:{worker_id}` key — orphaned increments self-clean on the next worker restart. Document this.
8. **What if Redis dies?** The scheduler can't read worker state; `pick_worker` raises `NoCapacityError` and the arq job retries. Workers can't heartbeat; their TTL keys expire after 15s; admin UI shows everything offline. **This is acceptable** — Redis dying is a wider outage than just acestep, the existing arq queue also runs on Redis, the whole job pipeline is down anyway. No special handling needed beyond surfacing a clear error.

## Cleanup (consolidated — what disappears)

Everything being removed by this refactor, in one place:

**Backend code (Phase 3):**
- `src/songmaker_cli/acestep_manager.py` — entire file
- `tests/test_acestep_manager.py` — entire file
- `_setup_acestep_manager`, `reinitialize_acestep` arq job, `_publish_acestep_status`, `_publish_acestep_loading_status` from `music_worker.py`
- `/acestep/status` and `/acestep/reinitialize` endpoints from `admin_api.py`
- `AceStepStatusResponse` from `api_models/settings.py` (line 188)
- `ACESTEP_*_REDIS_KEY`, `ACESTEP_PORT` constants from `constants.py` (verify with grep — referenced in `acestep_manager.py`, `music_worker.py`, `admin_api.py`, `acestep_engine/client.py`)
- `list_active_models` model-identity gate in `generation_api.py` (replaced by "any online worker exists" check)

**Frontend code (Phase 4):**
- `getAceStepStatus`, `reinitializeAceStep` from `frontend/src/lib/api/admin.ts`
- The current ACE-Step admin tab section (~75 lines) in `frontend/src/routes/settings/users/+page.svelte`
- Any TypeScript types referencing `AceStepStatusResponse` (regenerated by `scripts/generate_types.py`)

**Container / infra (Phase 3):**
- ACE-Step subprocess startup from the `songmaker-music-worker` service in `docker-compose.yml`
- `_models/acestep` volume mount from the music-worker
- GPU device reservation from the music-worker
- `huggingface_hub`, `acestep` deps from `Dockerfile.worker` (the music-worker dockerfile)

**Redis keys (Phase 3):**
- All `songmaker:acestep:*` keys from the **old** schema (status hash, loading status, port). The new schema uses `songmaker:acestep:worker:{id}` and `songmaker:acestep:queue:{id}` — they are namespaced differently. Consider a one-shot Redis cleanup at startup to `DEL` known-old keys, or just let them expire / accept the cruft.

**What is NOT deleted:**
- `src/acestep_engine/` — unchanged, still the HTTP client to the ACE-Step subprocess (now used from inside `acestep_worker/wrapper.py` instead of `acestep_manager.py`)
- `available_models` PG table — kept as-is, `is_active` is still the admin's allow-list
- `scripts/download_models.sh` — kept as the CLI escape hatch for fresh installs
- `MODEL_CONFIG_PATHS` constant — moves nowhere; still in `constants.py`

The size of this list is the sanity check. If a future reviewer reads the plan and doesn't see meaningful deletions, the refactor isn't real. This list is real.

## Verification

Per-phase verification is in each phase. End-to-end after Phase 4:

```bash
# Backend
ruff check src/ tests/ acestep_worker/
pytest tests/ -n auto -q --cov=songmaker_cli --cov=acestep_worker --cov=acestep_engine --cov-report=term-missing

# Frontend
cd frontend && pnpm check && pnpm lint && pnpm test

# Type sync
python scripts/generate_types.py  # verify no diff

# Containers
timeout 180 docker compose up -d --build --wait
docker compose ps  # all healthy
```

End-to-end manual smoke test (after Phase 4):

1. Open admin → ACE-Step tab. See **Worker Pool** card for `acestep-worker-0` with `Loaded: (none)` and `Status: Online`.
2. See **Model Registry** showing `sft`, `turbo`, `xl-sft` as downloaded; `xl-turbo` and `xl-base` as not downloaded.
3. Click "Load model" on the worker card, pick `xl-sft`. Card shows `Loading… target: xl-sft`. Wait 2-5 minutes. Card flips to `Loaded: xl-sft`.
4. In a song view, set model to `xl-sft`, click Generate. Job completes via the new scheduler path.
5. Switch model to `sft`. Worker card shows `Loading…` then flips. Generation works.
6. Toggle `xl-base` ON in the registry → fails with "Model not downloaded".
7. **(Phase 5)** Click Download on `xl-base` → progress bar appears. Wait. On completion, row updates.
8. Toggle `xl-base` ON → succeeds.
9. **(Phase 6)** Click "Restart" on worker card → worker SIGTERMs, docker healthcheck restarts, card briefly shows `Offline` then `Online: (none loaded)`.
10. (When 2nd GPU available): add `acestep-worker-1` to compose, `docker compose up -d`, the new card appears in the admin UI automatically. **Zero code change.**
