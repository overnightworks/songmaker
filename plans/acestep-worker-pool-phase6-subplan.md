# Phase 6 Sub-plan — Polish + observability + cleanup

> Concrete implementation plan for Phase 6 of [acestep-worker-pool.md](acestep-worker-pool.md). Phase 6 is the biggest phase so far — observability + several deferred features. The parent plan and the rewritten Phase 6 section both note this should ship as **two PRs** (observability first, UX/correctness second). This sub-plan respects that split. Read end-to-end before starting; this captures decisions that aren't in the parent plan and locks in the design decision for the trickiest item (the load-while-generating race).

## ⚠ READ THIS FIRST — state at start of Phase 6

- **Branch:** `feat/acestep-worker-pool` at `46a5187` (or later — verify with `git log --oneline -5`)
- **Phases shipped:** 1 (`c416194`), 2 (`275518c`), 3 (`74b8576` + follow-ups), 4 (`a1ca504` + review fixes `9c9937d` + spinner fix `aca35f6`), 5 (`a0e5136` backend + `574c84c` frontend + tightening `7ab326a`)
- **Recent inline fixes** that Phase 6 must NOT undo:
  - `b5a984d` — `is_model_downloaded` shard-aware (handles both single-file and sharded HF layouts)
  - `cf1fa5d` — heartbeat field name aligned (`loaded` not `loaded_models`)
  - `c32b246` — atomic `ModelCache.snapshot()` for cache state assembly
  - `c5a11e0` — heartbeat writer/reader contract test pinned at `tests/test_acestep_state.py::test_heartbeat_payload_keys_match_admin_reader`
  - `7ab326a` — Phase 5 download flag is atomic SET-NX (don't downgrade to naive SET)

**Heartbeat schema is locked by a regression test.** Items D7 (per-model VRAM size) and D8 (loading elapsed counter) below both extend the heartbeat payload — they MUST also extend the contract test in the same PR. The test currently asserts the writer publishes exactly the keys the reader expects; adding a new field without updating the test is allowed (the test only fails on missing/renamed keys), but adding a field on the writer without teaching the reader to consume it is silent data loss. The implementer is expected to extend the assertion to cover the new fields.

**`acestep_workers_total` and `acestep_workers_online` are already in `/health`** (added in Phase 3 cutover, [health_api.py:220-221](../src/songmaker_cli/health_api.py#L220-L221)). Phase 6 D1 mirrors them into Prometheus format under `/metrics`. Don't reinvent the read path — reuse the same `list_worker_identities` + `read_worker_state` calls.

**Worker startup retry already exists** but is bounded. [registry_client.py:13](../src/acestep_worker/registry_client.py#L13) defines `DEFAULT_RETRY_DELAYS_SECONDS = (1.0, 2.0, 5.0, 10.0, 30.0)` — 5 attempts (~48 s total), then raises `RegistrationFailedError` and the worker dies. Phase 6 D2 makes this indefinite + healthcheck-integrated.

**Generations are lock-free at the cache layer.** Verified by reading `model_cache.py:77` (`get_loaded` is a plain dict read with no lock) and `wrapper.py:128` (the `/generate` endpoint calls `get_loaded` then spawns a background task). The cache `asyncio.Lock` is only held by `load()`, `evict()`, and `evict_all()`. **The race in Phase 6 D6 is real:** an admin `/load_model` for a different mode can call `_evict_to_fit` and evict a model that's currently in use by a running generation. The generation will then crash with a stale subprocess handle.

## ⚠ READ THIS SECOND — PR split

Phase 6 ships as **two PRs**, in this order:

### PR 1 — Observability
Items: D1 (worker metrics), D2 (worker startup retry/healthcheck), D3 (operator docs metric keys + Redis namespace).

**Why first:** these are the foundation operators need to debug PR 2 in production. They're also mostly mechanical — extend an existing metrics formatter, replace a tuple of retry delays with a generator, write some markdown. Low design risk, low conflict surface.

**Estimate:** ~3–4 hours.

### PR 2 — UX + correctness
Items: D4 (restart endpoint), D5 (pin_model + LRU exemption), D6 (load-while-generating race fix), D7 (per-loaded-model VRAM size), D8 (loading elapsed counter), D9 (download auto-retry), D10 (operator docs troubleshooting + restart procedure).

**Why second:** D6 is the trickiest call in the whole project so far — it touches the cache lock semantics, the generation entry point, AND the `/load_model` semantics. Getting it wrong means generations crash mid-run. PR 1's observability gives the operator the tools to *see* if D6 broke anything in production.

**Estimate:** ~6–8 hours.

**Do not merge PR 2 before PR 1 is in production for at least one smoke test cycle.** If something in D6 regresses generation reliability, you want PR 1's metrics to catch it.

## Surprises found during exploration

1. **The `/health` endpoint already has worker count fields** (`acestep_workers_total`, `acestep_workers_online`). The original Phase 6 framing made it sound like Phase 6 was inventing this from scratch. It's not — it's promoting an existing data point from JSON to Prometheus. Less work than the original list implies.

2. **Worker startup retry partially exists** with a bounded delay tuple. Re-uses well — Phase 6 D2 just changes the strategy from "iterate over a fixed tuple" to "yield from a generator that loops forever after exhausting the tuple". ~5 LOC change in the retry function.

3. **`MusicWorkerSettings.functions` is a list, not a tuple.** Don't propose tuple syntax in any Phase 6 changes that touch arq settings.

4. **The `_iterate_task_events` async generator from Phase 5** is now the canonical SSE consumer in `scheduler.py`. Phase 6 D9 (download retry) reuses it via `consume_download_task_stream` — no new SSE plumbing needed.

5. **The atomic SET-NX tightening from `7ab326a`** (download flag is `set ... ex=N nx=True` returning bool) is what makes D9 (download retry) safe. Without that, retrying could re-acquire a flag the previous attempt was still holding. The retry implementation in D9 must call `clear_download_in_progress` between attempts so SET-NX can re-acquire.

6. **`docker-compose.yml:147`** the acestep-worker healthcheck currently tests `http://localhost:8001/health`, which returns 200 OK as soon as the FastAPI server starts — *before* registration with the control plane. D2's healthcheck integration changes the worker's `/health` endpoint to return 503 until `RegistryClient.register()` succeeds. The compose healthcheck stays unchanged; the *worker's* endpoint becomes more honest.

## D1. Worker metrics in `/metrics` (PR 1)

### Where to add the code

[src/songmaker_cli/health_api.py](../src/songmaker_cli/health_api.py) has the existing `/metrics` endpoint at line 117 and a `_format_prometheus()` helper at line 55. Both stay; D1 extends them.

The pattern: `metrics_endpoint` does its data gathering before formatting, then calls `_format_prometheus(...)` with named kwargs. Phase 6 adds:

```python
# new in metrics_endpoint, added to the existing data-gathering block
from songmaker_cli.acestep_state import read_queue_depth, read_worker_state
from songmaker_cli.db.queries import list_worker_identities

with ctx.db() as session:
    workers = list_worker_identities(session)

worker_states: list[tuple[str, dict | None, int]] = []
for w in workers:
    state = await read_worker_state(pool, w.id)
    qd = await read_queue_depth(pool, w.id)
    worker_states.append((w.id, state, qd))

acestep_workers_online = sum(1 for _, s, _ in worker_states if s is not None)
acestep_workers_loading = sum(
    1 for _, s, _ in worker_states if s is not None and s.get("target_loading")
)
acestep_workers_offline = len(worker_states) - acestep_workers_online
```

(`pool` comes from `get_arq_pool()` — already imported in `health_api.py:179` for the `/health` endpoint. Refactor the get to module-level if both endpoints need it.)

### What to format

`_format_prometheus()` gets new kwargs: `worker_states`, `acestep_workers_online`, `acestep_workers_loading`, `acestep_workers_offline`. It emits:

```
# HELP songmaker_acestep_workers_total Total registered acestep workers by status
# TYPE songmaker_acestep_workers_total gauge
songmaker_acestep_workers_total{status="online"} 1
songmaker_acestep_workers_total{status="loading"} 0
songmaker_acestep_workers_total{status="offline"} 0

# HELP songmaker_acestep_worker_loaded_models Number of loaded models per worker
# TYPE songmaker_acestep_worker_loaded_models gauge
songmaker_acestep_worker_loaded_models{worker_id="acestep-worker-0"} 2

# HELP songmaker_acestep_worker_queue_depth Queue depth per worker (Redis)
# TYPE songmaker_acestep_worker_queue_depth gauge
songmaker_acestep_worker_queue_depth{worker_id="acestep-worker-0"} 0
```

### Histograms — defer to a follow-up

The parent plan listed three histograms:
- `songmaker_acestep_model_load_duration_seconds{mode="..."}`
- `songmaker_acestep_generation_duration_seconds{mode="..."}`
- `songmaker_acestep_download_duration_seconds{mode="..."}` (added in the Phase 6 doc rewrite)

**Histograms need persistent state across requests** (bucket counts accumulate). The current `/metrics` endpoint is stateless — it pulls everything from PG/Redis on each request. Adding histograms means either:
- (a) Stand up a `prometheus_client` Counter/Histogram registry in `app.state` and write to it from the relevant code paths (jobs.py, generation_api.py, scheduler.py)
- (b) Compute approximate histograms from PG `Job.started_at`/`completed_at` columns on each `/metrics` request

**Decision:** ship gauges only in PR 1. Histograms are a follow-up — either Phase 6.5 or Phase 7. The gauges alone are enough to alert on "no online workers" and "queue depth growing", which is the primary observability gap. Document this deferral in the `docs/acestep.md` metric keys section.

### Tests

In `tests/test_health_api.py` (or wherever the existing `/metrics` test lives — verify with grep before writing):

- `test_metrics_includes_worker_status_gauges` — seed two workers (one online, one offline), assert the response body contains all three `songmaker_acestep_workers_total{status="..."}` lines with correct counts
- `test_metrics_loaded_models_per_worker` — seed worker with `loaded=["sft", "xl-sft"]`, assert `songmaker_acestep_worker_loaded_models{worker_id="..."} 2`
- `test_metrics_queue_depth_per_worker` — seed worker with queue_depth=3 in Redis, assert the gauge reflects it
- `test_metrics_no_workers_returns_zero_gauges` — empty PG → all gauges report 0, no errors

## D2. Worker startup retry rewrite + healthcheck integration (PR 1)

### Indefinite retry with cap-and-jitter backoff

Replace [registry_client.py:13](../src/acestep_worker/registry_client.py#L13)'s `DEFAULT_RETRY_DELAYS_SECONDS` tuple with a generator that yields the bounded prefix once, then yields the cap forever:

```python
from collections.abc import Iterator
import random

INITIAL_BACKOFF_SCHEDULE: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0)
INDEFINITE_BACKOFF_SECONDS: float = 60.0
JITTER_FRACTION: float = 0.2


def _retry_delays() -> Iterator[float]:
    yield from INITIAL_BACKOFF_SCHEDULE
    while True:
        jitter = INDEFINITE_BACKOFF_SECONDS * JITTER_FRACTION * (2 * random.random() - 1)
        yield INDEFINITE_BACKOFF_SECONDS + jitter
```

`RegistryClient.__init__` keeps the `retry_delays_seconds` parameter for backward compatibility (existing tests pass a fixed tuple), but its default becomes `_retry_delays`, and `register()` iterates `for delay in self._delays` (works on both tuples and iterators). **Subtle:** an iterator is single-use — if `register()` is called twice on the same client, the second call gets an exhausted iterator. Solution: `self._delays_factory` is a callable that returns a fresh iterator each call. The tests can pass a `lambda: iter([0.0, 0.0])` for fast tests.

Remove `RegistrationFailedError` raising at the end of the retry loop. The new contract: `register()` returns when (and only when) registration succeeds. The caller can `asyncio.wait_for(client.register(...), timeout=...)` if it needs a deadline.

### Healthcheck integration

The worker's `/health` endpoint at [wrapper.py:88](../src/acestep_worker/wrapper.py#L88) currently returns `HealthResponse(status="ok")` unconditionally. Make it return 503 until registration completes:

1. Add `registered: bool = False` to `WorkerDeps`.
2. The `lifespan` context manager at `wrapper.py:177` currently calls `await deps.registry_client.register(deps.registration)` synchronously. Change it to spawn the registration as a background task and let the FastAPI server come up immediately. When `register()` returns, set `deps.registered = True`.
3. Update `/health` to check `deps.registered`:
   ```python
   @router.get("/health", response_model=HealthResponse)
   async def health() -> HealthResponse:
       if not deps.registered:
           raise HTTPException(status_code=503, detail="awaiting control plane registration")
       return HealthResponse(status="ok")
   ```
4. The docker-compose healthcheck at [docker-compose.yml:147](../docker-compose.yml#L147) is unchanged — `curl -f` already treats 5xx as unhealthy.

**Why background task instead of blocking startup:** if registration is blocking and the control plane is slow, the worker's HTTP server never comes up, so even debug requests like `curl localhost:8001/health` time out. Background-task means the server is up immediately, the operator can see the failure mode in `/health` (503 with the detail message), and the worker keeps trying forever instead of dying after 48 s.

### Container log surfacing

Add a single startup log line at the top of `lifespan`:

```python
log.info(
    "acestep-worker %s starting; awaiting control plane at %s",
    deps.worker_id, deps.registry_client._control_plane_url if deps.registry_client else "(disabled)",
)
```

The existing per-attempt warning log (`"Registration attempt %d failed: %s. Retrying in %.1fs"`) stays.

### Tests

In `tests/acestep_worker/test_registry_client.py`:

- `test_retry_delays_yields_initial_then_indefinite` — pull 10 values from `_retry_delays()`, assert first 5 match `INITIAL_BACKOFF_SCHEDULE`, next 5 are within `INDEFINITE_BACKOFF_SECONDS ± JITTER_FRACTION`
- `test_register_succeeds_eventually_after_failures` — fake httpx that fails 7 times then succeeds; `register()` returns success without raising
- `test_register_calls_sleeper_with_jittered_value` — capture the sleeper calls, assert delays are within the jitter window

In `tests/acestep_worker/test_wrapper.py`:

- `test_health_returns_503_until_registered` — build deps with `registered=False`, hit `/health`, assert 503; flip `registered=True`, assert 200
- `test_lifespan_spawns_registration_background_task` — monkey-patch `register` to be slow (~0.1s); enter the lifespan; assert `/health` is up (503) immediately, assert `registered` flips to True after the background task completes

## D3. Operator docs — metric keys + Redis namespace section (PR 1)

[docs/acestep.md](../docs/acestep.md) gets a new top-level section: **"Operating the worker pool"**, placed after the existing "Model Variants" section and before the Phase 5 download paragraph. Contents:

### Subsection 1: Prometheus metric keys

Lists every `songmaker_acestep_*` metric with help text and example query. The list mirrors what D1 shipped — gauges only in PR 1. Histograms get a one-line "deferred" note pointing to the parent plan.

### Subsection 2: Redis key namespace reference

Operators need to know what's in Redis to debug stuck state. Document:

| Key pattern | Set by | Read by | TTL | Purpose |
|---|---|---|---|---|
| `songmaker:acestep:worker:{worker_id}` | acestep-worker heartbeat (every 5 s) | admin_api `/admin/workers`, scheduler `pick_worker`, `/health`, `/metrics` | 15 s | Ephemeral worker state (`loaded`, `target_loading`, `vram_used_gb`, `vram_total_gb`, `available_modes`, `queue_depth`, `last_heartbeat_at`) |
| `songmaker:acestep:queue:{worker_id}` | scheduler `incr_queue_depth`/`decr_queue_depth` (per generation dispatch) | admin_api, scheduler picker | none | Per-worker generation queue depth (atomic counter) |
| `songmaker:acestep:download:{mode}` | `download_model_on_worker` arq job (atomic SET-NX) | admin endpoint pre-check, arq job duplicate guard | 1800 s | Download-in-progress flag; value is the job_id |

### Subsection 3: Worker startup procedure

Brief, operator-facing:

1. Worker starts, FastAPI server up immediately
2. `/health` returns 503 with "awaiting control plane registration"
3. Background task tries to register, retries with exponential backoff (1s → 2s → 5s → 10s → 30s → 60s ± 20% forever)
4. Once registered, `/health` returns 200, container is healthy, traffic flows

If the worker is stuck, check container logs for the per-attempt warning lines and verify the control plane URL is reachable from the worker container.

**No troubleshooting playbooks in PR 1** — those go in PR 2's D10 along with the restart procedure.

## D4. Restart endpoint (PR 2)

### Worker side

Add `POST /api/internal/restart` to the worker's [wrapper.py](../src/acestep_worker/wrapper.py). The endpoint sits inside `build_router(deps)` next to the existing routes:

```python
@router.post("/restart")
async def restart() -> dict:
    log.info("Restart requested via /restart endpoint")
    pid = os.getpid()
    # Schedule SIGTERM after the response is sent
    loop = asyncio.get_running_loop()
    loop.call_later(0.1, lambda: os.kill(pid, signal.SIGTERM))
    return {"status": "restarting", "pid": pid}
```

The `call_later(0.1, ...)` defers SIGTERM by 100 ms so the HTTP response can be flushed to the caller before the process exits. The docker healthcheck restarts the container (it's running with `restart: unless-stopped` in compose).

**Auth:** the worker's HTTP server has no auth today (it's only reachable from inside the docker network). The control plane reaches it via the internal token. **Wait — the worker side doesn't currently check the internal token on its endpoints.** Verify by reading `wrapper.py` end-to-end. If true, document this as accepted (the worker is on a private docker network) and don't add auth. If the control plane *does* expect to send the token, the restart endpoint should check it for symmetry.

### Web side

Add `POST /api/admin/workers/{worker_id}/restart` to [admin_api.py](../src/songmaker_cli/admin_api.py):

```python
@router.post("/workers/{worker_id}/restart")
async def restart_worker_endpoint(
    worker_id: str,
    db: Session = Depends(get_db_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> StatusResponse:
    worker = get_worker_identity(db, worker_id)
    if worker is None:
        raise HTTPException(404, f"Worker '{worker_id}' not found")

    try:
        response = await _post_to_worker(worker.host, worker.port, "/restart")
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Worker unreachable: {exc}")
    if response.status_code >= 400:
        raise HTTPException(502, f"Worker returned {response.status_code}")
    return StatusResponse(status="restarting")
```

This is structurally identical to the existing `evict_model_on_worker_endpoint`. Reuse `_post_to_worker` from `admin_api.py`.

### Frontend

In [admin.ts](../frontend/src/lib/api/admin.ts):

```typescript
export async function restartWorker(workerId: string): Promise<void> {
    await apiFetch(`/api/admin/workers/${workerId}/restart`, { method: 'POST' });
}
```

Re-export from `client.ts`.

In [WorkerPoolPanel.svelte](../frontend/src/lib/components/WorkerPoolPanel.svelte) — Phase 4 explicitly omitted the Restart button. Add it back to the card-actions row:

```svelte
<button
    class="action-btn danger"
    onclick={() => handleRestart(worker.identity.id)}
    disabled={busyAction[`${worker.identity.id}:restart`]}
>
    {busyAction[`${worker.identity.id}:restart`] ? 'Restarting…' : 'Restart'}
</button>
```

The handler:
```typescript
async function handleRestart(workerId: string): Promise<void> {
    if (!confirm(`Restart worker ${workerId}? In-flight generations will fail.`)) return;
    busyAction = { ...busyAction, [`${workerId}:restart`]: true };
    try {
        await restartWorker(workerId);
        addToast(`Restart requested for ${workerId}`, 'info');
    } catch (e) {
        actionError = e instanceof Error ? e.message : 'Restart failed';
    } finally {
        busyAction = { ...busyAction, [`${workerId}:restart`]: false };
    }
}
```

The `confirm()` is intentional — restart kills in-flight generations. Make the operator confirm.

### Tests

- `test_restart_endpoint_kills_process` — mock `os.kill`, hit `/restart`, assert `os.kill(pid, SIGTERM)` was scheduled
- `test_restart_endpoint_returns_before_kill` — verify the `call_later` defers the kill until after the response
- `test_admin_restart_proxies_to_worker` — happy path
- `test_admin_restart_unknown_worker_404`
- `test_admin_restart_worker_unreachable_502`
- `test_admin_restart_requires_admin` — non-admin → 403

Frontend `admin.test.ts`:
- `test_restartWorker_POSTs_to_admin_endpoint`

## D5. `pin_model` LRU exemption + admin UI button (PR 2)

### Cache changes

Extend `ModelCache` ([model_cache.py](../src/acestep_worker/model_cache.py)) with a `_pinned: set[str]`:

```python
class ModelCache:
    def __init__(self, ...) -> None:
        ...
        self._pinned: set[str] = set()

    async def pin(self, mode: str) -> None:
        async with self._lock:
            if mode not in self._loaded:
                raise ModelNotLoadedError(f"Cannot pin {mode}: not loaded")
            self._pinned.add(mode)

    async def unpin(self, mode: str) -> None:
        async with self._lock:
            self._pinned.discard(mode)

    def is_pinned(self, mode: str) -> bool:
        return mode in self._pinned
```

`_evict_to_fit` skips pinned modes:

```python
async def _evict_to_fit(self, incoming_size_gb: float) -> list[str]:
    evicted: list[str] = []
    used = sum(self._sizes.get(m, 0.0) for m in self._loaded)
    while self._loaded and used + incoming_size_gb > self._budget_gb:
        # Find the LRU non-pinned victim
        victim_mode = next(
            (m for m in self._loaded if m not in self._pinned),
            None,
        )
        if victim_mode is None:
            raise CapacityError(
                f"Cannot fit {incoming_size_gb:.1f}GB: all loaded models are pinned",
            )
        ...
```

`evict()` should also refuse to evict a pinned model (raise `CapacityError` or just return `[]`?). **Decision:** `evict()` is an explicit admin operation, so it should *unpin and evict* — the admin asked for it. Document this in the docstring: "evict() implicitly unpins."

### Heartbeat schema

Add `pinned: list[str]` to the heartbeat payload in `wrapper.py::build_state_payload`:

```python
async def build_state_payload(deps: WorkerDeps) -> dict[str, Any]:
    snapshot = deps.cache.snapshot()
    return {
        "loaded": list(snapshot.loaded),
        "pinned": list(snapshot.pinned),  # NEW
        "target_loading": snapshot.target_loading,
        ...
    }
```

`CacheStateSnapshot` (in `model_cache.py`) gets a new `pinned: tuple[str, ...]` field. The atomic `snapshot()` method captures it under the lock, so no race.

**Heartbeat contract test must be extended** ([test_acestep_state.py::test_heartbeat_payload_keys_match_admin_reader](../tests/test_acestep_state.py)). The test asserts the writer publishes exactly the keys the reader consumes. Update both the writer assertion and `_state_from_dict` in `admin_api.py` to handle the new `pinned` field.

`api_models/workers.py::WorkerEphemeralState` gets `pinned: list[str] = []`.

### Web side

```python
class PinModelRequest(BaseModel):
    mode: str = Field(min_length=1, max_length=20)


@router.post("/workers/{worker_id}/pin_model")
async def pin_model_on_worker_endpoint(
    worker_id: str,
    req: PinModelRequest,
    ...
) -> StatusResponse:
    # Validate, _post_to_worker("/pin_model", {"mode": req.mode}), return ok
```

Same pattern for `/unpin_model`.

### Frontend

In [WorkerPoolPanel.svelte](../frontend/src/lib/components/WorkerPoolPanel.svelte) — Phase 4 explicitly omitted the Pin button. Add it back, one button per loaded model in the actions row, next to the Evict button:

```svelte
{#each worker.state.loaded as loadedMode (loadedMode)}
    {@const isPinned = (worker.state.pinned ?? []).includes(loadedMode)}
    <button
        class="action-btn"
        onclick={() => handleTogglePin(worker.identity.id, loadedMode, isPinned)}
        disabled={busy || busyAction[`${worker.identity.id}:pin:${loadedMode}`]}
    >
        {isPinned ? '📌 Pinned' : '📍 Pin'}
    </button>
    <button class="action-btn" onclick={() => handleEvict(...)}>Evict {loadedMode}</button>
{/each}
```

(Strip the emojis if it conflicts with the rest of the UI's icon style — verify before shipping.)

### Tests

- `test_cache_pin_unpin_basic`
- `test_cache_pin_unknown_mode_raises`
- `test_cache_evict_to_fit_skips_pinned`
- `test_cache_evict_to_fit_capacity_error_when_all_pinned`
- `test_cache_evict_implicitly_unpins`
- `test_cache_snapshot_includes_pinned_field`
- `test_heartbeat_payload_includes_pinned` (extend the contract test)
- `test_admin_pin_model_endpoint_*`

## D6. Load-while-generating race fix — DESIGN LOCKED: per-mode refcount (PR 2)

**This is the trickiest item in Phase 6.** Locking the design here so the implementer doesn't have to redesign mid-implementation.

### The race (verified by reading the code)

1. Generation A starts: `/generate` endpoint calls `cache.get_loaded("sft")` (no lock), gets the LoadedModel, spawns the runner via `spawn_background`. Runner is now executing against `loaded.handle` (a SubprocessHandle pointing to the running ACE-Step subprocess).
2. Admin issues `POST /load_model {"mode": "xl-base"}`. The endpoint enters `cache.load("xl-base")`, takes the lock.
3. `xl-base` doesn't fit alongside `sft`. `_evict_to_fit` picks `sft` as the LRU victim, calls `_unloader(sft_loaded_model)`, which sends SIGTERM to the subprocess.
4. Generation A's runner is mid-call to the (now-dead) subprocess. The HTTP call to `127.0.0.1:8101/generate` fails with ConnectError. The runner emits an `error` SSE event. The user sees their generation crash.

### The fix: refcount + acquire/release API

Add `_in_use: dict[str, int]` to `ModelCache`. Two new methods:

```python
async def acquire_for_use(self, mode: str) -> LoadedModel | None:
    async with self._lock:
        loaded = self._loaded.get(mode)
        if loaded is None:
            return None
        self._loaded.move_to_end(mode)
        self._in_use[mode] = self._in_use.get(mode, 0) + 1
        return loaded


async def release(self, mode: str) -> None:
    async with self._lock:
        if mode not in self._in_use:
            return
        self._in_use[mode] -= 1
        if self._in_use[mode] <= 0:
            del self._in_use[mode]
```

`_evict_to_fit` skips in-use modes (and pinned modes from D5):

```python
async def _evict_to_fit(self, incoming_size_gb: float) -> list[str]:
    evicted: list[str] = []
    used = sum(self._sizes.get(m, 0.0) for m in self._loaded)
    while self._loaded and used + incoming_size_gb > self._budget_gb:
        victim_mode = next(
            (m for m in self._loaded
             if m not in self._pinned and self._in_use.get(m, 0) == 0),
            None,
        )
        if victim_mode is None:
            raise CapacityError(
                f"Cannot fit {incoming_size_gb:.1f}GB: all eligible models are "
                f"in use or pinned (loaded={list(self._loaded)}, "
                f"in_use={dict(self._in_use)}, pinned={list(self._pinned)})",
            )
        victim_model = self._loaded[victim_mode]
        await self._unloader(victim_model)
        del self._loaded[victim_mode]
        used -= self._sizes.get(victim_mode, 0.0)
        evicted.append(victim_mode)
    return evicted
```

`evict(mode)` (the explicit admin op) refuses to evict an in-use mode:

```python
async def evict(self, mode: str) -> list[str]:
    async with self._lock:
        if mode not in self._loaded:
            return []
        if self._in_use.get(mode, 0) > 0:
            raise CapacityError(
                f"Cannot evict {mode}: in use by "
                f"{self._in_use[mode]} in-flight tasks",
            )
        await self._unloader(self._loaded[mode])
        del self._loaded[mode]
        self._pinned.discard(mode)
        return [mode]
```

### The `/generate` endpoint becomes

```python
@router.post("/generate", response_model=TaskCreatedResponse)
async def generate(req: GenerateRequest) -> TaskCreatedResponse:
    loaded = await deps.cache.acquire_for_use(req.mode)
    if loaded is None:
        raise HTTPException(
            status_code=409,
            detail=f"Mode {req.mode} not loaded; call /load_model first",
        )
    task_id = await deps.task_store.create("generate")

    async def _runner_with_release() -> None:
        try:
            await deps.generate_runner(
                deps.task_store, task_id,
                mode=req.mode, config=req.config,
                port=loaded.port, audio_output_dir=deps.audio_output_dir,
            )
        finally:
            await deps.cache.release(req.mode)

    spawn_background(_runner_with_release())
    return TaskCreatedResponse(task_id=task_id)
```

The `_runner_with_release` wrapper guarantees `release` runs even if the runner crashes. The acquire happens *before* the spawn so the endpoint can return 409 if the model isn't loaded.

### Why not the alternatives

**Refuse with 409 (option b in the parent doc):** doesn't fix the race, just makes it harder to hit. If two admin actions race, one still wins and one crashes.

**Queue load after generation drains (option c):** complex state machine, ~3x the code, and the user has to wait silently. Refcount is simpler and the failure mode (CapacityError) is honest — the admin sees "all loaded models in use, retry when generations finish" and can act on it.

### admin endpoint side effect

`POST /api/admin/workers/{id}/load_model` can now return 503 (via the arq job's eventual `_update_job(... failed ..., error_type="capacity_blocked")`) if all loaded models are in use. The arq job catches `CapacityError` from the worker's response and surfaces it as a clean failure. The admin sees the failure in the existing job-tracking UI from Phase 4.

### Tests

- `test_cache_acquire_for_use_increments_count`
- `test_cache_release_decrements_count`
- `test_cache_release_unknown_mode_no_op`
- `test_cache_evict_to_fit_skips_in_use`
- `test_cache_evict_to_fit_skips_pinned_and_in_use`
- `test_cache_evict_to_fit_capacity_error_when_all_locked`
- `test_cache_evict_refuses_in_use`
- `test_generate_endpoint_acquires_and_releases_via_wrapper` — mock the runner, verify acquire was called before spawn and release was called in finally
- `test_generate_endpoint_releases_on_runner_exception`
- `test_load_model_returns_capacity_error_when_loaded_in_use` — full integration: acquire `sft`, try to load `xl-base` (which would need to evict `sft`), verify CapacityError surfaces

### What about the cache `_lock` deadlock risk?

`acquire_for_use` and `release` both take `self._lock`. The runner calls `release` from within an async task. If the runner is awaiting on something else that's blocked on the lock, we'd deadlock. **Verified safe:** the runner only takes the lock briefly (incr/decr a dict), and never calls back into other locked methods. No deadlock.

## D7. Per-loaded-model VRAM size in the Worker Pool admin UI (PR 2)

### Heartbeat schema change

The current heartbeat payload publishes `loaded: list[str]`. Change to `loaded: list[{"mode": str, "size_gb": float}]`. Update:

1. **`acestep_worker/wrapper.py::build_state_payload`** — change the `"loaded"` field to a list of dicts. The size comes from `cache._sizes[mode]` (already known per-mode).
2. **`acestep_worker/model_cache.py::CacheStateSnapshot`** — change `loaded: tuple[str, ...]` to `loaded: tuple[LoadedModelInfo, ...]` where `LoadedModelInfo` is a small dataclass with `mode: str` and `size_gb: float`.
3. **`songmaker_cli/admin_api.py::_state_from_dict`** — change `loaded=list(state.get("loaded", []))` to parse the new shape: `loaded=[LoadedModelDetail(**m) for m in state.get("loaded", [])]`.
4. **`api_models/workers.py::WorkerEphemeralState`** — change `loaded: list[str]` to `loaded: list[LoadedModelDetail]` where `LoadedModelDetail` is a new Pydantic model.
5. **`scripts/generate_types.py`** — add `LoadedModelDetail` to the emit list.
6. **`frontend/src/lib/components/WorkerPoolPanel.svelte`** — update the "Loaded:" row rendering to show "{mode} ({size_gb} GB)".
7. **`tests/test_acestep_state.py::test_heartbeat_payload_keys_match_admin_reader`** — extend the assertion to check the new shape: `state.loaded[0].mode == "sft"` and `state.loaded[0].size_gb == 6.0`.
8. **`scheduler.py::_PickedWorker.loaded_modes`** — currently `list[str]`. Update to extract just the mode names from the new shape: `loaded_modes=[m["mode"] for m in state.get("loaded", [])]`. The picker doesn't care about size, only presence.

**Watch for cascade:** `pick_worker`'s `_pick_from` does `if target_mode in w.loaded_modes` — this stays `list[str]` for the picker's purposes. The richer shape only flows to the admin UI.

### Tests

- `test_heartbeat_publishes_loaded_with_size`
- `test_state_from_dict_parses_loaded_detail`
- `test_picker_extracts_mode_names_from_new_shape`
- `test_admin_workers_response_includes_loaded_size_per_model`

## D8. "Loading X… (1m 23s elapsed)" counter on Worker Pool cards (PR 2)

### Heartbeat schema change

Add `loading_started_at: str | None` to the heartbeat payload. Set when `cache.load()` enters its `_target_loading = mode` block, clear in `finally`. The atomic snapshot (`c32b246`) means the field is consistent with `target_loading`.

In `model_cache.py`:

```python
self._target_loading: str | None = None
self._loading_started_at: datetime | None = None  # NEW

# in load(), after self._target_loading = mode:
self._loading_started_at = datetime.now(timezone.utc)

# in load()'s finally:
self._target_loading = None
self._loading_started_at = None
```

`CacheStateSnapshot` gets `loading_started_at: datetime | None`. `build_state_payload` serializes it to ISO string. `_state_from_dict` parses it. `WorkerEphemeralState` gets `loading_started_at: str | None`.

Frontend `WorkerPoolPanel.svelte::describeStatus` becomes:

```typescript
function describeStatus(worker: WorkerInfoItem): string {
    const state = worker.state;
    if (!state) return 'Offline (no heartbeat)';
    if (state.target_loading) {
        const elapsed = state.loading_started_at
            ? formatRelativeElapsed(state.loading_started_at)
            : null;
        return elapsed
            ? `Loading ${state.target_loading}… (${elapsed} elapsed)`
            : `Loading ${state.target_loading}…`;
    }
    if (state.loaded.length === 0) return 'No model loaded';
    if (state.queue_depth > 0) return `Busy (${state.queue_depth} in queue)`;
    return 'Idle';
}
```

`formatRelativeElapsed(iso)` returns "1m 23s" / "47s" / "12m". Tiny helper, file-local.

**Heartbeat contract test must be extended** for both the new field and the new shape from D7.

### Tests

- `test_cache_load_sets_loading_started_at` (already partially tested by `target_loading` semantics)
- `test_heartbeat_publishes_loading_started_at_during_load`
- `test_loading_started_at_cleared_after_load`

## D9. Download auto-retry policy (3 attempts) (PR 2)

The Phase 5 sub-plan deferred this. Implementation in [jobs.py::download_model_on_worker](../src/songmaker_cli/jobs.py):

```python
DOWNLOAD_MAX_ATTEMPTS = 3


async def download_model_on_worker(ctx, job_id: str, mode: str) -> None:
    # ... existing setup, mode validation, redis flag acquire ...

    last_error: str | None = None
    for attempt in range(1, DOWNLOAD_MAX_ATTEMPTS + 1):
        try:
            # ... existing pick_worker, POST /download_model, consume_download_task_stream ...
            _update_job(factory, job_id, "completed", progress=1.0)
            return
        except WorkerTaskFailed as exc:
            last_error = f"Download failed (attempt {attempt}): {exc}"
            log.warning("download attempt %d/%d failed: %s", attempt, DOWNLOAD_MAX_ATTEMPTS, exc)
        except httpx.HTTPError as exc:
            last_error = f"SSE transport failed (attempt {attempt}): {exc}"
        # Wait before retry, with cap-and-jitter
        if attempt < DOWNLOAD_MAX_ATTEMPTS:
            await asyncio.sleep(5.0 * attempt)

    _update_job(
        factory, job_id, "failed",
        error=last_error or "All download attempts exhausted",
        error_type="download_error",
    )
```

**Critical:** the Redis flag stays acquired across all attempts. The existing `try/finally` already handles this — `clear_download_in_progress` runs at the end of the whole function, not per-attempt. **Don't move the clear inside the loop** or each retry would re-acquire the flag and a concurrent admin click could slip through between attempts.

**Idempotent retry on the worker side:** HF `snapshot_download` is naturally idempotent — it skips files whose content hash matches. So retry #2 picks up where retry #1 left off via the HF cache. No worker-side change needed.

**Don't retry on `invalid_mode`, `no_workers`, `worker_unreachable`, or `worker_error`** — those are pre-flight failures that won't fix themselves in 5 seconds. Only retry on `WorkerTaskFailed` (the SSE error event from the worker, which can be transient HF rate limits or network blips) and `httpx.HTTPError` (transient SSE drops).

### Tests

- `test_download_retries_on_worker_task_failed_then_succeeds`
- `test_download_retries_on_sse_transport_then_succeeds`
- `test_download_does_not_retry_on_worker_unreachable`
- `test_download_does_not_retry_on_invalid_mode`
- `test_download_fails_after_max_attempts_with_last_error`
- `test_download_redis_flag_held_across_retries`

## D10. Operator docs — troubleshooting playbooks + restart procedure (PR 2)

[docs/acestep.md](../docs/acestep.md) "Operating the worker pool" section gets four new subsections (appended to the D3 sections from PR 1):

### Subsection 4: Worker restart procedure

How an admin restarts a worker via the UI, what happens to in-flight generations (they fail with `error_type=worker_unreachable`), how to verify the restart succeeded (heartbeat returns within ~10 s, status flips from offline → online).

### Subsection 5: pin_model semantics

How pinning works, when to use it (single-GPU multi-user with a "must always be loaded" preference), what happens when all models are pinned and a new load is requested (CapacityError, admin must explicitly unpin first).

### Subsection 6: Troubleshooting playbooks

- **"Worker won't register"** — check `/health` for the 503 detail message, check container logs, verify the control plane URL and internal token
- **"Download stalls"** — check `songmaker:acestep:download:{mode}` Redis key, check the arq job status, check worker logs for HF errors
- **"Load fails with CapacityError"** — list pinned and in-use models from the admin UI, identify which generations are blocking the load, either wait or evict explicitly
- **"Stale-job reaper killed my generation"** — explain the reaper, the heartbeat mechanism, the per-event `_touch_heartbeat` calls, how to debug if a long generation is being killed unexpectedly

### Subsection 7: Updating docs/acestep.md

A note that the architecture diagrams in `docs/architecture.md` cover the cross-cutting flow, while `docs/acestep.md` is the worker-pool-specific reference. Cross-link both.

## D11. Files Touched (Phase 6)

### PR 1 — Observability

| File | Change |
|---|---|
| `src/songmaker_cli/health_api.py` | Extend `/metrics` endpoint with worker pool gauges. Refactor `_format_prometheus` to take new kwargs. |
| `src/acestep_worker/registry_client.py` | Replace bounded `DEFAULT_RETRY_DELAYS_SECONDS` tuple with `_retry_delays` generator (initial schedule then indefinite cap-and-jitter). Remove `RegistrationFailedError` from the success path. |
| `src/acestep_worker/wrapper.py` | `WorkerDeps` gets `registered: bool = False`. Lifespan spawns `register()` as a background task. `/health` returns 503 until registered. |
| `src/acestep_worker/__main__.py` | If needed, plumb the new `registered` flag — verify whether the lifespan or `__main__` owns the state. |
| `tests/test_health_api.py` | New tests for the worker pool metric gauges. |
| `tests/acestep_worker/test_registry_client.py` | New tests for indefinite retry generator + delay window. |
| `tests/acestep_worker/test_wrapper.py` | New tests for `/health` 503-until-registered + lifespan spawn behavior. |
| `docs/acestep.md` | New "Operating the worker pool" section with metric keys, Redis namespace reference, worker startup procedure. |

### PR 2 — UX + correctness

| File | Change |
|---|---|
| `src/acestep_worker/model_cache.py` | Add `_in_use: dict[str, int]`, `_pinned: set[str]`, `_loading_started_at: datetime \| None`. New methods: `acquire_for_use`, `release`, `pin`, `unpin`, `is_pinned`. Update `_evict_to_fit` to skip in-use and pinned. Update `evict` to refuse in-use and implicitly unpin. Update `CacheStateSnapshot` shape. |
| `src/acestep_worker/wrapper.py` | `/generate` becomes `acquire_for_use` + spawn-with-release wrapper. New `/restart`, `/pin_model`, `/unpin_model` endpoints. `build_state_payload` publishes `loaded` as list of dicts, plus `pinned` and `loading_started_at`. |
| `src/acestep_worker/models.py` | Add `PinModelRequest`, `UnpinModelRequest`. |
| `src/songmaker_cli/admin_api.py` | New endpoints: `/admin/workers/{id}/restart`, `/admin/workers/{id}/pin_model`, `/admin/workers/{id}/unpin_model`. Update `_state_from_dict` for the new heartbeat shape. |
| `src/songmaker_cli/api_models/workers.py` | Add `LoadedModelDetail`, `PinModelOnWorkerRequest`, `UnpinModelOnWorkerRequest`. Update `WorkerEphemeralState.loaded` to `list[LoadedModelDetail]`. Add `pinned: list[str]` and `loading_started_at: str \| None`. |
| `src/songmaker_cli/scheduler.py` | Update `_list_online_workers` to extract mode names from the new `loaded` shape. |
| `src/songmaker_cli/jobs.py` | `download_model_on_worker` gets the 3-attempt retry loop. |
| `scripts/generate_types.py` | Add `LoadedModelDetail` to `_RESPONSE_MODEL_NAMES` and `_EMIT_ORDER`. Regenerate `frontend/src/lib/api/types.ts`. |
| `frontend/src/lib/api/admin.ts` | Add `restartWorker`, `pinModelOnWorker`, `unpinModelOnWorker`. Re-export from client.ts. |
| `frontend/src/lib/components/WorkerPoolPanel.svelte` | Wire Restart button (with confirm dialog). Wire Pin/Unpin button per loaded model. Update "Loaded:" row to show per-model size. Update `describeStatus` to compute elapsed time from `loading_started_at`. |
| `tests/acestep_worker/test_model_cache.py` | New tests for refcount, pinning, evict refusal, capacity error, snapshot shape, loading_started_at. |
| `tests/acestep_worker/test_wrapper.py` | New tests for `/generate` acquire-release wrapper, `/restart` endpoint, `/pin_model` endpoint, heartbeat new fields. |
| `tests/test_acestep_state.py` | Extend the heartbeat contract test for `loaded` shape, `pinned`, `loading_started_at`. |
| `tests/test_admin_api.py` | New endpoint tests. |
| `tests/test_jobs.py` | Download retry tests. |
| `tests/test_scheduler.py` | Verify picker works against the new heartbeat shape. |
| `frontend/src/lib/api/admin.test.ts` | Add tests for `restartWorker`, `pinModelOnWorker`, `unpinModelOnWorker`. |
| `frontend/src/lib/api/types.ts` | Regenerated. |
| `docs/acestep.md` | Append subsections 4–7 (restart procedure, pin semantics, troubleshooting playbooks, cross-link to architecture.md). |

**Files NOT touched (in either PR):**

- `acestep_engine/` — engine isolation rule, no changes needed
- `acestep_worker/downloads.py` — Phase 5 work, complete
- `acestep_worker/heartbeat.py` — the loop machinery is fine, only the payload builder in `wrapper.py` changes
- Phase 7 / Phase 8 plan files — out of scope
- CLAUDE.md — Phase 7 territory

## D12. Implementation order

### PR 1 — Observability

1. **Read CLAUDE.md, this sub-plan, and the parent plan's Phase 6 section** (5 min)
2. **Verify branch base** — `git log --oneline -5` should show `46a5187` or later (1 min)
3. **`registry_client.py` rewrite** — replace tuple with `_retry_delays` generator + factory pattern. (20 min)
4. **`tests/acestep_worker/test_registry_client.py`** — new tests for indefinite retry. (20 min)
5. **HARD checkpoint #1:** `pytest tests/acestep_worker/test_registry_client.py -q`. Existing tests must still pass with the factory-pattern refactor. (5 min)
6. **`wrapper.py` lifespan + `/health`** — add `registered: bool` to deps, spawn registration as background task, return 503 until registered. (20 min)
7. **`tests/acestep_worker/test_wrapper.py`** — new health-503 + lifespan tests. (30 min)
8. **HARD checkpoint #2:** `pytest tests/acestep_worker/ -q`. Full worker test suite green. (5 min)
9. **`health_api.py` `/metrics` extension** — add the data-gathering block, extend `_format_prometheus`. (30 min)
10. **`tests/test_health_api.py`** — new gauge tests. (40 min)
11. **`docs/acestep.md` "Operating the worker pool" section, subsections 1–3** (metric keys, Redis namespace, worker startup procedure). (40 min)
12. **HARD checkpoint #3:** full backend test sweep + `pnpm check`. Ruff + pytest -q --ignore scoring. (15 min)
13. **Self-review pass.** (15 min)
14. **Commit + push** as `feat(phase6-pr1): worker pool observability + indefinite registration retry`. (5 min)
15. **Smoke test** is the user's job. Brief them, wait for go. **Do not start PR 2 until PR 1 has passed at least one production smoke test cycle.**

### PR 2 — UX + correctness

16. **Pull latest from origin** to ensure PR 1 is in. Re-verify the branch base. (1 min)
17. **`model_cache.py` refcount + pin** (D5 + D6 cache changes) — add `_in_use`, `_pinned`, `acquire_for_use`, `release`, `pin`, `unpin`, update `_evict_to_fit` and `evict`. (45 min)
18. **`tests/acestep_worker/test_model_cache.py` for refcount + pin** — comprehensive: increment, decrement, eviction-skip, capacity-error, evict-refusal, implicit-unpin-on-evict. (60 min)
19. **HARD checkpoint #4:** `pytest tests/acestep_worker/test_model_cache.py -q`. The cache layer must be airtight before touching the wrapper. (5 min)
20. **`wrapper.py` `/generate` rewrite** — switch to `acquire_for_use` + `_runner_with_release`. Add new endpoints: `/restart`, `/pin_model`, `/unpin_model`. (40 min)
21. **`tests/acestep_worker/test_wrapper.py`** — generate acquire/release wrapper tests, restart endpoint tests, pin endpoint tests. (60 min)
22. **HARD checkpoint #5:** `pytest tests/acestep_worker/ -q`. (5 min)
23. **Heartbeat schema changes** — `model_cache.py::CacheStateSnapshot`, `wrapper.py::build_state_payload`, `acestep_state.py` reader (if needed), `admin_api.py::_state_from_dict`. The new fields: `loaded` shape change, `pinned`, `loading_started_at`. (45 min)
24. **`api_models/workers.py`** — `LoadedModelDetail`, `WorkerEphemeralState` updates. (15 min)
25. **`tests/test_acestep_state.py::test_heartbeat_payload_keys_match_admin_reader`** — extend the assertion for all three new fields. **Don't skip this** — it's the contract test that catches the bug Phase 3 hit. (20 min)
26. **`scheduler.py::_list_online_workers`** — extract mode names from new shape. (5 min)
27. **`tests/test_scheduler.py`** — verify picker works against new shape. (20 min)
28. **`scripts/generate_types.py` + regenerate `types.ts`** — add `LoadedModelDetail`. (10 min)
29. **`admin_api.py` new endpoints** — restart, pin_model, unpin_model. (30 min)
30. **`tests/test_admin_api.py`** — endpoint tests. (40 min)
31. **`jobs.py` download retry loop** — D9. (20 min)
32. **`tests/test_jobs.py` retry tests** — D9. (40 min)
33. **HARD checkpoint #6:** full backend sweep. `unset VIRTUAL_ENV && uv run ruff check src/ tests/ && uv run pytest tests/ -n auto -q --ignore=tests/test_scorers.py --ignore=tests/test_scorers_extended.py`. (15 min)
34. **`frontend/src/lib/api/admin.ts`** — restartWorker, pinModelOnWorker, unpinModelOnWorker. Re-export. (10 min)
35. **`frontend/src/lib/api/admin.test.ts`** — three new tests. (15 min)
36. **`frontend/src/lib/components/WorkerPoolPanel.svelte`** — restart button (with confirm), pin/unpin button per loaded model, per-model VRAM size in the Loaded row, loading elapsed counter in `describeStatus`. (60 min)
37. **`docs/acestep.md` subsections 4–7** — restart procedure, pin semantics, troubleshooting playbooks, cross-link. (60 min)
38. **HARD checkpoint #7:** `pnpm check && pnpm lint && pnpm test`. (10 min)
39. **Self-review pass.** (30 min)
40. **Commit + push** as 1–2 commits per the Phase 4/5 convention. Suggested split: backend (cache + wrapper + admin + tests + docs) and frontend (admin.ts + WorkerPoolPanel + test). (10 min)
41. **Smoke test** — user's job. The smoke test for PR 2 is significant: verify generation does NOT crash when an admin loads a different model mid-generation; verify pin/unpin works; verify restart works; verify download retry works.

Total wall clock: PR 1 ~3 hours, PR 2 ~7 hours.

## D13. Test strategy

### Critical tests (catch the most bugs)

PR 1:
1. **`test_metrics_includes_worker_status_gauges`** — exact response body assertions, not just status code 200
2. **`test_register_succeeds_eventually_after_failures`** — fake httpx with 7 failures then success, register() returns without raising
3. **`test_health_returns_503_until_registered`** — flip the boolean, observe 503 → 200

PR 2:
4. **`test_cache_evict_to_fit_skips_in_use`** — load A, acquire A, try to load B that requires evicting A → CapacityError, A is still loaded
5. **`test_generate_endpoint_releases_on_runner_exception`** — runner raises mid-execution, refcount returns to 0
6. **`test_load_model_returns_capacity_error_when_loaded_in_use`** — full integration test: acquire `sft`, POST `/load_model {"mode": "xl-base"}`, observe failure with CapacityError
7. **`test_heartbeat_payload_keys_match_admin_reader`** (extended) — verify `loaded` shape, `pinned`, `loading_started_at` all round-trip from writer to reader without key drift
8. **`test_download_retries_on_worker_task_failed_then_succeeds`** — first attempt raises, second succeeds, job ends "completed"
9. **`test_download_redis_flag_held_across_retries`** — set the flag at start, mock the consumer to fail twice, verify the flag is NOT cleared between attempts

### Tests to avoid

- ❌ Mocking the cache and asserting `acquire_for_use` was called (tests the test, not the impl)
- ❌ Asserting `os.kill` was called from `/restart` without verifying the response was sent first
- ❌ Mocking the entire heartbeat and asserting it was published (vacuous)
- ❌ Frontend "renders without crashing" tests (they catch nothing)

### Coverage expectation

100% on all new code:
- `model_cache.py` additions (refcount, pin, evict_to_fit changes, snapshot shape)
- `registry_client.py` retry rewrite
- `wrapper.py` new endpoints + `/generate` wrapper + `/health` 503 branch
- `admin_api.py` new endpoints
- `jobs.py::download_model_on_worker` retry loop
- `acestep_state.py` no new code in Phase 6

## D14. Self-review checklist (before each commit)

1. **Re-read every changed file via `git diff HEAD~N`**. No skipping.
2. **Heartbeat contract test extended for every new field.** This is the rule Phase 3 invented; Phase 6 honors it.
3. **No comments in new code** (per `feedback_code_standards.md`). Module-level docstrings are fine; inline comments are not.
4. **Refcount paired:** every `acquire_for_use` has a matching `release` in a `finally` block. Grep `acquire_for_use` and verify each call site.
5. **Redis flag for downloads:** clear is in `finally`, NOT inside the retry loop. Verify by reading the diff.
6. **Background tasks:** `register()` and `_runner_with_release` are spawned with `spawn_background` (or `asyncio.create_task` with strong-reference tracking). No fire-and-forget orphans.
7. **No new heartbeat fields without contract-test extension.** Grep `build_state_payload` and `_state_from_dict` for new keys; verify they appear in the test.
8. **Frontend `$effect` race-fix pattern:** every new `$effect` that watches `activeJobs` uses a plain `let` for bookkeeping, NOT `$state`. Repeat-trap from Phases 4 and 5.
9. **No hardcoded mode names in new code.** Use `MODEL_CONFIG_PATHS`.
10. **Ruff clean.** `unset VIRTUAL_ENV && uv run ruff check src/ tests/`.
11. **Full backend test suite green.** Same `--ignore` set as Phases 4/5.
12. **Frontend check + lint + test.** All three.
13. **`scripts/generate_types.py --check`** is no-op.

## D15. Things to watch out for

### Watchpoint 1: The `_iterate_task_events` empty-stream bug pattern

Phase 5 implementation hit this: an async generator that doesn't `return` after a clean stream end will infinite-loop in any retry/reconnect wrapper. **Verify the new `_runner_with_release` wrapper in `/generate` handles all cleanup paths** — runner returns normally, runner raises an exception, runner is cancelled. The `try/finally` in the wrapper covers all three.

### Watchpoint 2: Refcount leak on cancel

If the runner is cancelled (`asyncio.CancelledError`), Python re-raises the cancellation through `finally`. The `release` call in `finally` MUST run before re-raise. The standard `try/finally` pattern handles this — don't try to "improve" it with custom cancellation handling.

### Watchpoint 3: The 100 ms delay in `/restart` is critical

```python
loop.call_later(0.1, lambda: os.kill(pid, signal.SIGTERM))
```

If you change the delay to 0 or omit `call_later`, the SIGTERM fires before the HTTP response is flushed. The admin sees a connection-reset error instead of `{"status": "restarting"}`. Test it: use httpx to call the endpoint and assert the response body is parsed before the connection drops.

### Watchpoint 4: Heartbeat contract test extension is non-negotiable

The Phase 3 incident: `loaded_models` vs `loaded` writer/reader mismatch broke the entire admin UI. The contract test was added explicitly to prevent this from recurring. **Every PR 2 commit that adds a heartbeat field must extend this test in the same commit.** Don't split them.

### Watchpoint 5: `_list_online_workers` cascade

Updating `state.get("loaded", [])` from `list[str]` to `list[dict]` cascades to:
- `_PickedWorker.loaded_modes` (still wants strings for the picker)
- `_state_from_dict` (admin endpoint)
- `WorkerEphemeralState` schema
- Frontend `WorkerInfoItem.state.loaded` type
- Generated `types.ts`

Miss any of these and you get a runtime KeyError or a TypeScript build error. The implementer should grep `state.get("loaded"` and `\.loaded` repo-wide and verify each call site.

### Watchpoint 6: The `pinned` field appears in admin_api `_state_from_dict`

Phase 5 review found that `_state_from_dict` was reading `state.get("loaded", [])` not `state.get("loaded_models", [])` because of the `cf1fa5d` fix. **Read `_state_from_dict` end-to-end before adding the new fields** — make sure the new keys (`pinned`, `loading_started_at`, the loaded shape change) all flow through cleanly.

### Watchpoint 7: `evict_all` and pinned models on shutdown

`cache.evict_all()` is called in the lifespan shutdown to drain the GPU. If models are pinned, should `evict_all` skip them? **No** — shutdown is shutdown, drain everything. `evict_all` ignores both pin and refcount. Document this in the docstring.

### Watchpoint 8: Restart endpoint and the `/health` poll loop

After `/restart` fires SIGTERM, the docker healthcheck on the *outside* will see /health fail (connection refused) and the container will be marked unhealthy. Compose `restart: unless-stopped` will then bring it back up. The new container will go through D2's "registering, /health is 503" phase before flipping to healthy. **Smoke test:** verify the admin UI's Worker Pool panel goes through `online → offline → loading → online` over the restart cycle.

### Watchpoint 9: PR 2 backend tests will be slow

Adding refcount + pin + new heartbeat fields touches ~6 test files. Running them under xdist is fine but the iteration time grows. Use `pytest tests/acestep_worker/test_model_cache.py -q` for tight loops, save the full sweep for HARD checkpoints.

### Watchpoint 10: Don't roll the prometheus_client dependency in PR 1

`prometheus_client` is a real package and the right long-term tool, but adding it now means PR 1 also adds a dep. Resist. The `_format_prometheus` function in `health_api.py` is plain string formatting and works fine for gauges. Histograms (deferred per D1) will need real `prometheus_client` if/when they ship — that's the time to add the dep, not PR 1.

### Watchpoint 11: The Phase 4 `$effect` self-write trap, again

Worker Pool panel changes in PR 2 (D5 pin button, D7 VRAM size, D8 elapsed counter) all touch `WorkerPoolPanel.svelte`. **Don't introduce a new `$effect` that writes to its own bookkeeping `$state`.** The `let trackedLoadJobIds = new Set<string>()` pattern is correct; a `$state(new Set<string>())` would crash the browser with `effect_update_depth_exceeded`. Reference the existing pattern at [WorkerPoolPanel.svelte:28](../frontend/src/lib/components/WorkerPoolPanel.svelte#L28).

### Watchpoint 12: HF rate limit is the most likely cause of download retry firing

If the operator hammers Download repeatedly during testing, HF's CDN may rate-limit. The retry loop will then fire 3x with 5s/10s/15s delays before failing. **Test the retry path with a deliberate fake rate-limit response from the worker** — don't try to trigger a real one against HF in CI.

## D16. What is NOT in Phase 6 (deferred)

- **Histograms** (`model_load_duration_seconds`, `generation_duration_seconds`, `download_duration_seconds`) — D1 deferred to a follow-up because they need persistent state across requests. Phase 6.5 or Phase 7.
- **`prometheus_client` dependency** — same reason, deferred with histograms.
- **Auto-pin on first load** — pinning is admin-explicit in v1. Not in Phase 6.
- **Cache eviction policy beyond LRU** (LFU, score-based) — out of scope.
- **Multi-host worker coordination** — single-host architecture stays.
- **Generation queue persistence across worker restart** — out of scope; restart kills in-flight generations by design.
- **Frontend tests for Worker Pool panel DOM rendering** — Phase 4 deferred this; still deferred unless `@testing-library/svelte` becomes a dep.
- **CLAUDE.md updates** — Phase 7 territory.
- **Phase 7 cleanup sweep** — separate phase.
- **Phase 8 image refactor** — separate phase.

If you find yourself implementing any of these in Phase 6, **stop**.

## D17. Branching + commits

Phase 6 commits go on `feat/acestep-worker-pool` (the same branch as Phases 1–5).

**PR 1 commit split (suggested 2 commits):**
1. `feat(phase6-pr1): indefinite worker registration retry + healthcheck integration` — `registry_client.py`, `wrapper.py` lifespan + `/health`, all worker tests
2. `feat(phase6-pr1): worker pool gauges in /metrics + operator docs` — `health_api.py`, `tests/test_health_api.py`, `docs/acestep.md` subsections 1–3

**PR 2 commit split (suggested 2 commits):**
1. `feat(phase6-pr2): backend — refcount, pin, restart, heartbeat schema, download retry` — all backend changes (model_cache, wrapper, admin_api, jobs, scheduler, api_models, generate_types, contract test extension)
2. `feat(phase6-pr2): frontend — restart/pin/VRAM/elapsed in WorkerPoolPanel + docs` — admin.ts, types.ts (regenerated), WorkerPoolPanel.svelte, admin.test.ts, docs/acestep.md subsections 4–7

Push to `origin/feat/acestep-worker-pool` after each commit (so the user can review incrementally).

## D18. Smoke test plan (PR 1 + PR 2)

### PR 1 smoke test

1. `timeout 300 docker compose up -d --build --wait songmaker-acestep-worker-0 songmaker-web` — both rebuilt
2. `curl http://localhost:8080/api/admin/metrics` (or whatever the public path is — verify) and grep for `songmaker_acestep_workers_total`. Expect:
   ```
   songmaker_acestep_workers_total{status="online"} 1
   songmaker_acestep_workers_total{status="loading"} 0
   songmaker_acestep_workers_total{status="offline"} 0
   ```
3. `docker compose stop songmaker-acestep-worker-0`. Wait 20 s (heartbeat TTL is 15 s). Re-curl `/metrics`. Expect `online=0, offline=1`.
4. `docker compose start songmaker-acestep-worker-0`. Curl `http://localhost:8001/health` from inside the container immediately — expect 503 with the "awaiting control plane" detail. Wait ~5 s, re-curl — expect 200.
5. **Failure mode test:** stop the web container. `docker compose stop songmaker-web`. Restart the worker. Watch the worker logs: should see "awaiting control plane at http://songmaker-web:8080" and per-attempt failure warnings every ~1 → 60 s. Bring the web container back up. Within 60 s the worker should successfully register and `/health` should flip to 200.

### PR 2 smoke test

1. Same rebuild
2. Open admin UI → ACE-Step tab
3. **Pin test:** load `sft` on the worker. Click Pin on `sft`. Verify the badge shows "📌 Pinned". Try to load `xl-base` (which would need to evict `sft`). Expect a clean failure with "all eligible models are pinned" in the error message. Click Unpin on `sft`. Try the load again — should succeed.
4. **Refcount test (the critical one):**
   - Load `sft`. Start a real generation against `sft` from the main UI (not the admin tab).
   - Switch to the admin tab. While the generation is running, click Load model → `xl-base`.
   - Expected: Load fails with "Cannot fit ... in use by 1 in-flight tasks". The running generation completes successfully without crashing.
   - Wait for the generation to finish. Try the load again — should succeed.
5. **Restart test:** click Restart on the worker. Confirm the dialog. Expected: card flips offline → loading → online over ~10 s. In-flight generations (if any) fail with `worker_unreachable`.
6. **Per-model VRAM test:** verify the "Loaded:" row shows "sft (6 GB), xl-sft (12 GB)" instead of just "sft, xl-sft".
7. **Elapsed counter test:** issue a Load on a not-loaded model, watch the card. Status should show "Loading xl-base… (5s elapsed)" updating every poll tick.
8. **Download retry test:** stop the acestep-worker container. Click Download on `xl-base`. The first attempt POST should fail (worker unreachable). The arq job should NOT retry on `worker_unreachable` (per D9). Bring the worker back up. Click Download again — should succeed.
9. **Heartbeat contract test in production:** `docker compose exec redis redis-cli GET 'songmaker:acestep:worker:acestep-worker-0'` and verify the JSON has `loaded` (list of dicts), `pinned` (list of strings), `loading_started_at` (ISO string or null). Compare against what the admin UI shows — they should match.

## D19. Quick context for next session

If you're a new agent picking this up: read `CLAUDE.md`, then [acestep-worker-pool.md](acestep-worker-pool.md), then this file. Phase 1 = `c416194`, Phase 2 = `275518c`, Phase 3 = `74b8576`, Phase 4 = `aca35f6` + review fixes, Phase 5 = `574c84c` + tightening `7ab326a`, Phase 6 docs rewrite = `46a5187`. Branch is `feat/acestep-worker-pool`.

The biggest single risk in Phase 6 is **D6 (the load-while-generating race fix)**. The design is locked in this sub-plan: per-mode refcount + acquire/release API. **Do not redesign** — implement what's specified. If you find a flaw in the design, surface it for user review before changing direction.

The second-biggest risk is **the heartbeat schema cascade** (D7 + D8 + Watchpoint 5). Three new fields touch six files. The contract test added in `c5a11e0` is the safety net — extend it in the same commit as the schema change, not later.

The third-biggest risk is **shipping PR 1 and PR 2 together**. Don't. PR 1's observability is what catches PR 2 regressions in production. Ship PR 1, smoke test, ship PR 2.
