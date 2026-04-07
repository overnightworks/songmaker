# Phase 5 Sub-plan — UI-driven downloads with progress

> Concrete implementation plan for Phase 5 of [acestep-worker-pool.md](acestep-worker-pool.md). Phase 5 wires the (already-disabled) Download button in the Phase 4 Model Registry panel through to a real worker download, with progress streaming via the existing `/api/jobs/{id}/stream` SSE pipeline. Read end-to-end before starting; this captures decisions that aren't in the parent plan and corrects several drift points.

## ⚠ READ THIS FIRST — parent plan is stale on Phase 5

**The parent plan describes Phase 5 as "implement `acestep_worker/downloads.py` (currently a stub) + add admin endpoint + frontend wiring." That's wrong on the first half.** `acestep_worker/downloads.py` is **already fully implemented** from Phase 1: 151 LOC of real code (8 functions including `is_model_downloaded`, `start_download`, `run_download`, `_poll_progress`, `hf_snapshot_download`, `spawn_background`) plus 271 LOC of comprehensive tests. The `/download_model` HTTP endpoint is already wired in `wrapper.py`. The `DownloadModelRequest` Pydantic model already exists. The `task_store` already supports `kind="download"`. The container env (`HF_TOKEN`, `HF_HUB_DISABLE_XET=1`) is already set.

**Recent (today, immediately before Phase 5 was drafted) the worker-side download path was further hardened:**
- `b5a984d` — `is_model_downloaded` now correctly handles **both** single-file safetensors models (`sft`, `turbo`) **and** sharded HF layouts (`xl-sft`, `xl-base`, `xl-turbo`). `huggingface_hub.snapshot_download` natively downloads both layouts; the registry/UI source of truth is now `is_model_downloaded`.
- `c32b246` + `c5a11e0` — `ModelCache.snapshot()` is the atomic state read, and the heartbeat writer/reader contract is pinned by `tests/test_acestep_state.py::test_heartbeat_payload_keys_match_admin_reader`. **Phase 5 does NOT add new heartbeat fields.** If a future change does, that contract test must be extended.

**Phase 5's actual implementation scope is significantly smaller than the parent plan implies:**
1. Web-side `download_model_on_worker` arq job in `jobs.py`
2. Web-side `POST /api/admin/registry/{mode}/download` admin endpoint
3. Refactor `consume_task_stream` to extract reusable SSE iteration; add a download-flavored wrapper
4. Frontend Download button wiring in `ModelRegistryPanel.svelte` + new API client function
5. Tests for all of the above
6. One paragraph in `docs/acestep.md`

**Estimate:** ~6 hours (was ~10 in the parent plan's framing). No worker code changes needed.

## ⚠ READ THIS SECOND — what we're NOT doing on the SSE side

The parent plan says the arq job "SSE-subscribes to the worker task stream and forwards events to the existing `/api/jobs/{job_id}/stream`". That phrasing implies bidirectional SSE multiplexing. **It's wrong.** The existing `/api/jobs/{id}/stream` endpoint at [generation_api.py:449](../src/songmaker_cli/generation_api.py#L449) is a **PG poller**: it polls the `Job` row every `SSE_POLL_INTERVAL_SECONDS` (1 s) and emits an SSE event when `status` or `progress` changes. **It does not consume worker SSE.**

**What Phase 5 actually does:** the arq job opens an `httpx.stream` to the worker's `/tasks/{task_id}/stream`, parses progress events, and writes them into the PG `Job` row via `_update_job(... progress=fraction)`. The existing `/api/jobs/{id}/stream` endpoint sees the PG row change on its next 1-second poll and pushes the new progress to the browser.

**We are NOT** building a parallel SSE channel, NOT extending `/api/jobs/{id}/stream`, NOT introducing pub/sub, and NOT doing SSE-to-SSE multiplexing. The arq job is a worker→PG bridge; the existing endpoint is the PG→browser bridge. They meet in the middle at the `Job` row.

## State at start of Phase 5

- **Branch:** `feat/acestep-worker-pool` (Phase 1 = `c416194`, Phase 2 = `275518c`, Phase 3 = `74b8576`, Phase 4 = `aca35f6` + heartbeat field-name fix `cf1fa5d` + the in-flight model_cache heartbeat race fix from the parallel agent)
- **Already shipped from Phase 1 (parent plan calls these "stub" — they're not):**
  - `src/acestep_worker/downloads.py` — **fully implemented**: `is_model_downloaded`, `list_available_modes`, `directory_size_bytes`, `hf_snapshot_download`, `_poll_progress`, `run_download`, `start_download`, `spawn_background`. ~150 LOC, real code, not a stub.
  - `tests/acestep_worker/test_downloads.py` — **271 LOC, ~13 tests**, full coverage of all branches: success, unknown mode, network failure, partial-download recovery, sharded layout detection, progress polling, zero-expected-size guard, HF token threading, background-task tracking.
  - `src/acestep_worker/wrapper.py:145` — `POST /download_model` endpoint **already wired** to `start_download`. Returns `TaskCreatedResponse(task_id=...)`.
  - `src/acestep_worker/models.py:37` — `DownloadModelRequest(BaseModel)` already defined.
  - `src/acestep_worker/task_store.py` — supports `kind="download"` (the task store is generic over kind).
  - **Container env:** `HF_TOKEN` and `HF_HUB_DISABLE_XET=1` are already set on `acestep-worker-0` in [docker-compose.yml:141-142](../docker-compose.yml#L141-L142) and [docker/acestep-worker.Dockerfile:24](../docker/acestep-worker.Dockerfile#L24). No env work needed.
- **Phase 4 frontend stub:** [ModelRegistryPanel.svelte](../frontend/src/lib/components/ModelRegistryPanel.svelte) renders a **disabled** Download button on every row with the tooltip "Coming in Phase 5". The button stays in place; Phase 5 just wires it.
- **Worker selection logic:** [scheduler.py:89](../src/songmaker_cli/scheduler.py#L89) `_list_online_workers` and `pick_worker` exist for generation dispatch. Downloads need a different policy (no `incr_queue_depth`, deterministic by id, no prefer-loaded heuristic).
- **SSE forwarding template:** [scheduler.py:191](../src/songmaker_cli/scheduler.py#L191) `consume_task_stream` already implements the worker `/tasks/{id}/stream` consumer with reconnect logic, but it's hardcoded to validate `done` payloads as `GenerationTaskResultDTO`. Downloads have a different `done` shape (`{"mode": ..., "size_bytes": ...}`). The reconnect/buffering logic is reusable.
- **Job stream UI:** [generation_api.py:449](../src/songmaker_cli/generation_api.py#L449) `api_stream_job` is the `/api/jobs/{id}/stream` SSE endpoint. It **polls the PG `Job` row** every `SSE_POLL_INTERVAL_SECONDS` and emits when `status` or `progress` changes. **It does not consume worker SSE.** This means Phase 5's arq job needs to *write* progress into the PG job row; the frontend gets it for free via the existing endpoint.

## Phase 5 goal (recap)

1. Admin clicks **Download** on a not-downloaded model in the Model Registry panel
2. Frontend `POST /api/admin/registry/{mode}/download` → backend creates a `Job` row + enqueues an arq job → returns `JobResponse`
3. Frontend `trackJob(job, { mode })` opens an EventSource on `/api/jobs/{id}/stream` (existing infrastructure)
4. Music-worker arq job picks a worker (any online, deterministic), POSTs `/download_model`, gets a worker `task_id`, opens `/tasks/{task_id}/stream`, and forwards progress events into the PG `Job` row via `_update_job(... progress=fraction)`
5. The `/api/jobs/{id}/stream` poll loop sees the progress changes and emits SSE to the browser
6. The Model Registry row shows a progress bar while the job is in `activeJobs`
7. On completion, the worker's next heartbeat updates `available_modes`, the registry panel's 5s poll picks up the new state, and the row flips to ✓ downloaded

## Surprises found during exploration (must address)

1. **`downloads.py` is not a stub.** Parent plan describes the worker side as "Phase 5 implementation" of a Phase 1 stub. **It's already done.** Phase 5 is web-side + frontend only on the implementation axis. This dramatically reduces scope. (The parent plan is wrong on this; treat the parent plan as draft/aspirational for Phase 5 worker code.)

2. **`/api/jobs/{id}/stream` polls PG, it doesn't multiplex worker SSE.** The parent plan says the arq job "SSE-subscribes to the task stream and forwards events to the existing `/api/jobs/{job_id}/stream`" — that wording implies SSE-to-SSE multiplexing. **Reality:** the endpoint is a PG poller. The arq job just needs to write `progress` to the PG row; the existing endpoint will surface it. No new SSE plumbing is needed on the web side. This is the same pattern that generation already uses.

3. **`consume_task_stream` is not reusable as-is** — it returns a `GenerationTaskResultDTO`. Downloads have a different `done` payload shape: `{"mode": "sft", "size_bytes": 12345678}`. The reconnect / SSE-parsing / event-loop logic IS reusable, but the result-validation step is generation-specific.

4. **Concurrent download requests for the same mode** can corrupt files (HF `snapshot_download` is not concurrency-safe). Not addressed in Phase 1's `downloads.py`. Needs decision: defer to Phase 6, or add a per-mode lock now? **Decision in D7 below.**

5. **The `/api/admin/registry` endpoint already computes `downloaded`** as the union of `available_modes` across worker heartbeats. So once the download finishes and the worker's next heartbeat publishes the new `available_modes`, the registry row updates automatically — no special "download finished, mark as downloaded" path needed.

## D1. SSE consumer reuse — extract a generic event iterator

The cleanest way to reuse `consume_task_stream`'s reconnect/parsing logic for downloads is to **extract the SSE consumption loop as a private async generator**, then have both the generation and download consumers wrap it with their type-specific result handling.

### The extracted primitive

```python
# in src/songmaker_cli/scheduler.py

async def _iterate_task_events(
    worker: _PickedWorker,
    task_id: str,
    *,
    options: DispatchOptions = DispatchOptions(),
) -> AsyncIterator[tuple[str, dict]]:
    """Yield (event_type, data) tuples from a worker's /tasks/{id}/stream.

    Reconnects on transport drop, raises after max_sse_reconnects exhausted.
    Stops yielding after a `done` or `error` event (caller decides what to
    do with them — both event types ARE yielded so the caller can validate
    the payload or surface the error message).
    """
    reconnects = 0
    timeout = httpx.Timeout(
        connect=options.sse_connect_timeout_seconds,
        read=options.sse_read_timeout_seconds,
        write=options.sse_connect_timeout_seconds,
        pool=options.sse_connect_timeout_seconds,
    )
    while True:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "GET",
                    f"{worker.base_url}/tasks/{task_id}/stream",
                    headers=_internal_headers(),
                ) as resp:
                    resp.raise_for_status()
                    buffer = ""
                    async for chunk in resp.aiter_text():
                        buffer += chunk
                        while "\n\n" in buffer:
                            raw, buffer = buffer.split("\n\n", 1)
                            parsed = _parse_sse_event(raw)
                            if parsed is None:
                                continue
                            event_type, data = parsed
                            yield event_type, data
                            if event_type in ("done", "error"):
                                return
        except (httpx.TransportError, httpx.RemoteProtocolError) as exc:
            reconnects += 1
            if reconnects > options.max_sse_reconnects:
                log.error(
                    "SSE reconnect budget exhausted for task %s on %s",
                    task_id, worker.id,
                )
                raise
            backoff = min(
                options.initial_reconnect_backoff_seconds * (2 ** (reconnects - 1)),
                options.max_reconnect_backoff_seconds,
            )
            log.warning(
                "SSE drop on %s task %s (attempt %d/%d): %s — reconnecting in %.1fs",
                worker.id, task_id, reconnects, options.max_sse_reconnects, exc, backoff,
            )
            await asyncio.sleep(backoff)
```

### `consume_task_stream` becomes a thin wrapper

```python
async def consume_task_stream(
    worker: _PickedWorker,
    task_id: str,
    *,
    on_progress: ProgressCallback | None = None,
    on_heartbeat: HeartbeatCallback | None = None,
    options: DispatchOptions = DispatchOptions(),
) -> GenerationTaskResultDTO:
    async for event_type, data in _iterate_task_events(worker, task_id, options=options):
        await _maybe_invoke(on_heartbeat)
        if event_type == "progress":
            fraction = float(data.get("progress", 0.0))
            await _maybe_invoke(on_progress, fraction)
        elif event_type == "done":
            result_payload = data.get("result") or {}
            try:
                return GenerationTaskResultDTO.model_validate(result_payload)
            except ValidationError as exc:
                raise WorkerTaskFailed(
                    f"Worker returned invalid result: {exc}",
                ) from exc
        elif event_type == "error":
            message = data.get("error") or "worker error"
            raise WorkerTaskFailed(message)
    raise WorkerTaskFailed("SSE stream ended without done/error event")
```

### `consume_download_task_stream` is the parallel for downloads

```python
class DownloadTaskResultDTO(BaseModel):
    mode: str
    size_bytes: int


async def consume_download_task_stream(
    worker: _PickedWorker,
    task_id: str,
    *,
    on_progress: ProgressCallback | None = None,
    on_heartbeat: HeartbeatCallback | None = None,
    options: DispatchOptions = DispatchOptions(),
) -> DownloadTaskResultDTO:
    async for event_type, data in _iterate_task_events(worker, task_id, options=options):
        await _maybe_invoke(on_heartbeat)
        if event_type == "progress":
            fraction = float(data.get("progress", 0.0))
            await _maybe_invoke(on_progress, fraction)
        elif event_type == "done":
            result_payload = data.get("result") or {}
            try:
                return DownloadTaskResultDTO.model_validate(result_payload)
            except ValidationError as exc:
                raise WorkerTaskFailed(
                    f"Worker returned invalid download result: {exc}",
                ) from exc
        elif event_type == "error":
            message = data.get("error") or "worker error"
            raise WorkerTaskFailed(message)
    raise WorkerTaskFailed("SSE stream ended without done/error event")
```

The two consumers are nearly identical wrappers around `_iterate_task_events`. ~25 LOC duplication, but each is independently testable and the result-type contract is explicit per call site. Considered factoring further (a generic `consume_task_stream_for[T]` with a Pydantic model parameter), but Python's generic-class machinery makes that uglier than the duplication.

**Risk:** the refactor of `consume_task_stream` must keep all existing scheduler tests passing. Critical tests to verify after refactor (from `tests/test_scheduler.py`):
- `test_consume_task_stream_done`
- `test_consume_task_stream_error`
- `test_consume_task_stream_progress_calls_callback`
- `test_consume_task_stream_reconnects_on_transport_error`
- `test_consume_task_stream_gives_up_after_max_reconnects`
- `test_dispatch_*` (the integration tests that exercise the full path)

Add:
- `test_iterate_task_events_yields_in_order`
- `test_iterate_task_events_stops_after_done`
- `test_iterate_task_events_stops_after_error`
- `test_iterate_task_events_reconnect_budget`
- `test_consume_download_task_stream_done`
- `test_consume_download_task_stream_error`
- `test_consume_download_task_stream_progress_calls_callback`
- `test_consume_download_task_stream_invalid_payload_raises`

## D2. Worker selection — `pick_any_online_worker`

Downloads don't compete for queue slots and don't need prefer-loaded. The parent plan says "first online worker sorted by id for determinism". Add:

```python
# in scheduler.py

async def pick_any_online_worker(
    db: Session, redis: Redis,
) -> _PickedWorker:
    workers = await _list_online_workers(db, redis)
    if not workers:
        raise NoCapacityError("No online ACE-Step workers")
    return min(workers, key=lambda w: w.id)
```

Two-line function. Stays in `scheduler.py` next to `pick_worker`. Tests:
- `test_pick_any_online_worker_returns_lowest_id` — three online workers, returns lex-smallest id
- `test_pick_any_online_worker_skips_offline` — three workers, only one with Redis state, returns it
- `test_pick_any_online_worker_no_workers_raises` — empty PG → `NoCapacityError`

## D3. The `download_model_on_worker` arq job

Lives in `src/songmaker_cli/jobs.py`, next to `load_model_on_worker`. Signature:

```python
async def download_model_on_worker(ctx, job_id: str, mode: str) -> None:
    import httpx

    from songmaker_cli.acestep_state import (
        clear_download_in_progress,
        set_download_in_progress,
    )
    from songmaker_cli.constants import MODEL_CONFIG_PATHS
    from songmaker_cli.internal_api import INTERNAL_TOKEN_ENV, INTERNAL_TOKEN_HEADER
    from songmaker_cli.scheduler import (
        DispatchOptions,
        NoCapacityError,
        WorkerTaskFailed,
        consume_download_task_stream,
        pick_any_online_worker,
    )
    from songmaker_cli.worker_base import _get_db_factory

    factory = _get_db_factory()
    _update_job(factory, job_id, "running", worker_pid=os.getpid())

    if mode not in MODEL_CONFIG_PATHS:
        _update_job(
            factory, job_id, "failed",
            error=f"Unknown model mode '{mode}'",
            error_type="invalid_mode",
        )
        return

    redis = ctx["redis"]
    await set_download_in_progress(redis, mode, job_id)
    try:
        try:
            with factory() as session:
                worker = await pick_any_online_worker(session, redis)
        except NoCapacityError as exc:
            _update_job(
                factory, job_id, "failed",
                error=str(exc),
                error_type="no_workers",
            )
            return

        token = os.environ.get(INTERNAL_TOKEN_ENV, "")
        headers = {INTERNAL_TOKEN_HEADER: token}
        submit_url = f"{worker.base_url}/download_model"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                submit = await client.post(submit_url, json={"mode": mode}, headers=headers)
        except httpx.HTTPError as exc:
            _update_job(
                factory, job_id, "failed",
                error=f"Worker unreachable: {exc}",
                error_type="worker_unreachable",
            )
            return

        if submit.status_code >= 400:
            _update_job(
                factory, job_id, "failed",
                error=f"Worker returned {submit.status_code}: {submit.text[:200]}",
                error_type="worker_error",
            )
            return

        task_id = submit.json()["task_id"]

        def _on_progress(fraction: float) -> None:
            _update_job(factory, job_id, "running", progress=fraction)
            _touch_heartbeat(factory, job_id)

        def _on_heartbeat() -> None:
            _touch_heartbeat(factory, job_id)

        try:
            await consume_download_task_stream(
                worker,
                task_id,
                on_progress=_on_progress,
                on_heartbeat=_on_heartbeat,
                options=DispatchOptions(),
            )
        except WorkerTaskFailed as exc:
            _update_job(
                factory, job_id, "failed",
                error=f"Download failed: {exc}",
                error_type="download_error",
            )
            return
        except httpx.HTTPError as exc:
            _update_job(
                factory, job_id, "failed",
                error=f"SSE transport failed: {exc}",
                error_type="sse_transport",
            )
            return

        _update_job(factory, job_id, "completed", progress=1.0)
    finally:
        await clear_download_in_progress(redis, mode)
```

Notes:
- `_touch_heartbeat` already exists at [jobs.py:710](../src/songmaker_cli/jobs.py#L710); it's the standard arq-job heartbeat refresh.
- The progress callback writes to PG synchronously — `_update_job` is sync via `factory()`. This is the same pattern `load_model_on_worker` uses.
- Throttling: the parent plan suggests SSE events arrive every ~2s (worker's `_poll_progress` interval). 2s between PG writes is fine — no throttling needed at this layer.

## D4. Music-worker registration

`src/songmaker_cli/music_worker.py` — append to `MusicWorkerSettings.functions` (verified: the actual class name is `MusicWorkerSettings`, not `WorkerSettings`, and `functions` is a **list** literal, not a tuple):

```python
functions = [generate, load_model_on_worker, download_model_on_worker]
```

Test in `tests/test_music_worker.py::test_music_worker_settings_functions` — bump expected count from 2 → 3 and assert `download_model_on_worker` is in the list.

## D5. Admin endpoint

`src/songmaker_cli/admin_api.py` — add at the bottom:

```python
@router.post("/registry/{mode}/download")
async def download_model_endpoint(
    mode: str,
    db: Session = Depends(get_db_session),
    pool: ArqRedis = Depends(get_arq_pool_dep),
    admin: AuthenticatedUser = Depends(require_admin),
) -> JobResponse:
    from songmaker_cli.acestep_state import read_worker_state
    from songmaker_cli.arq_pool import get_arq_pool
    from songmaker_cli.constants import ARQ_MUSIC_QUEUE_NAME
    from songmaker_cli.db.queries import (
        create_job,
        get_queue_position,
        list_worker_identities,
        update_job_status,
    )

    if mode not in MODEL_CONFIG_PATHS:
        raise HTTPException(400, f"Unknown model mode '{mode}'")

    workers = list_worker_identities(db)
    online = False
    for w in workers:
        if await read_worker_state(pool, w.id) is not None:
            online = True
            break
    if not online:
        raise HTTPException(503, "No online workers available to download")

    job = create_job(db, "download_model_on_worker", user_id=admin.id)
    db.commit()

    try:
        arq_pool = get_arq_pool()
        await arq_pool.enqueue_job(
            "download_model_on_worker", job.id, mode,
            _queue_name=ARQ_MUSIC_QUEUE_NAME,
        )
    except ConnectionError:
        update_job_status(db, job.id, "failed", error="Job queue unavailable")
        db.commit()
        raise HTTPException(503, "Job queue unavailable")

    return JobResponse.from_orm(job, queue_position=get_queue_position(db, job))
```

**Soft idempotency check (optional, recommend YES):** before enqueueing, also check if the model is already in the union of `available_modes` from any worker's heartbeat. If yes, return 409 with `"Model already downloaded"`. The frontend already disables the button when `model.downloaded === true`, but this is belt-and-suspenders and gives a useful error if the user races. **Decision in D7 below — leaning yes.**

**Path-param vs body:** `mode` is in the URL path, not the body. Reasons:
- Matches the parent plan: `POST /api/admin/registry/{mode}/download`
- Symmetric with the future `DELETE /api/admin/registry/{mode}` if eviction/uninstall is added later
- No request body needed at all (no `LoadModelOnWorkerRequest`-style wrapper class)

## D6. Frontend changes

### `frontend/src/lib/api/admin.ts`

```typescript
export async function downloadModel(mode: string): Promise<JobItem> {
    return apiFetch<JobItem>(`/api/admin/registry/${encodeURIComponent(mode)}/download`, {
        method: 'POST'
    });
}
```

Re-export from `client.ts`. Test in `admin.test.ts` (mocked fetch, asserts URL + method + parsed JobItem).

### `frontend/src/lib/components/ModelRegistryPanel.svelte`

Replace the disabled stub button with a real handler. The panel currently has no concept of `activeJobs` — it needs to subscribe (mirroring the WorkerPoolPanel pattern from Phase 4).

Concrete diff outline:

```svelte
<script lang="ts">
    // existing imports
    import { downloadModel } from '$lib/api/client';
    import { activeJobs, trackJob } from '$lib/stores/jobs';
    import { addToast } from '$lib/stores/toast';

    const DOWNLOAD_JOB_TYPE = 'download_model_on_worker';

    let busyMode = $state<Record<string, boolean>>({});
    let actionError = $state('');

    const downloadingByMode = $derived(
        new Map(
            $activeJobs
                .filter((j) => j.job.type === DOWNLOAD_JOB_TYPE && j.mode)
                .map((j) => [j.mode as string, j])
        )
    );

    let trackedDownloadJobIds = new Set<string>();
    $effect(() => {
        const current = new Set(
            $activeJobs.filter((j) => j.job.type === DOWNLOAD_JOB_TYPE && j.mode).map((j) => j.job.id)
        );
        let disappeared = false;
        for (const id of trackedDownloadJobIds) {
            if (!current.has(id)) {
                disappeared = true;
                break;
            }
        }
        if (disappeared) void store.refresh();
        trackedDownloadJobIds = current;
    });

    async function handleDownload(mode: string): Promise<void> {
        actionError = '';
        busyMode = { ...busyMode, [mode]: true };
        try {
            const job = await downloadModel(mode);
            trackJob(job, { mode });
            addToast(`Downloading ${mode}…`, 'info');
        } catch (e) {
            actionError = e instanceof Error ? e.message : 'Failed to start download';
        } finally {
            busyMode = { ...busyMode, [mode]: false };
        }
    }
</script>
```

Then in the table cell:

```svelte
{@const dlJob = downloadingByMode.get(model.mode)}
<td class="actions-col">
    {#if dlJob}
        <span class="dl-progress">
            Downloading… {Math.round((dlJob.job.progress ?? 0) * 100)}%
        </span>
    {:else if model.downloaded}
        <button class="action-btn" disabled title="Already downloaded">Downloaded</button>
    {:else}
        <button
            class="action-btn"
            onclick={() => handleDownload(model.mode)}
            disabled={busyMode[model.mode]}
        >
            {busyMode[model.mode] ? 'Starting…' : 'Download'}
        </button>
    {/if}
</td>
```

The same `$effect` race-fix pattern from Phase 4 (`trackedDownloadJobIds` as a plain `let`, not `$state`) applies. Don't re-introduce that bug.

**Progress bar vs percentage text:** start with text-only ("Downloading… 47%"). A real progress bar element is nice-to-have but not strictly needed; the parent plan says "inline progress bar" but a percentage is a strict subset of that information. Adding an actual `<progress>` element is ~5 LOC if we want to. Decision: text only in v1; add visual bar if it feels lacking during smoke test.

### `frontend/src/lib/api/admin.test.ts`

Add one test:

```typescript
it('downloadModel POSTs to registry endpoint and returns JobItem', async () => {
    mockOk({ id: 'j1', type: 'download_model_on_worker', status: 'queued', progress: 0 });
    const result = await downloadModel('xl-base');
    expect(result.id).toBe('j1');
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe('/api/admin/registry/xl-base/download');
    expect(init.method).toBe('POST');
});
```

## D7. Concurrent download requests for the same mode — solved via Redis flag in D8

**Original framing:** Two users (or two browser tabs) click Download for `xl-base` within seconds of each other. Two arq jobs created, both POST `/download_model` to (possibly the same) worker, two `run_download` background tasks start, both call `hf_snapshot_download` against the same target dir. HF `snapshot_download` is not concurrency-safe — partial files can interleave.

**Original decision (revised after Phase 5 sub-plan review):** the first draft of this sub-plan deferred this to Phase 6 on the grounds that it's a single-user platform and the frontend disable mitigates the same-tab case. Reviewer pushed back: the failure mode is **silent corruption of the HF cache**, which is much worse than rejecting one redundant click. Worth solving even on a single-user platform.

**Final decision:** solve it in Phase 5 via a Redis flag in the control plane. See D8 for the design. The flag uses a separate key namespace (`songmaker:acestep:download:*`), TTL 30 minutes, set in the arq job's `try` block and cleared in `finally`. The admin endpoint checks the flag before enqueueing and returns 409 if a download for the same mode is already running.

This is **option (b) revised:** the original "(b)" suggested extending the heartbeat schema, which was over-engineering. A standalone Redis key is the right primitive — it lives in the control plane (no worker code change), uses the existing arq Redis instance, and has natural expiry semantics for crash recovery.

**Frontend mitigation still ships:** the Download button is disabled while `dlJob` is in `activeJobs` for that mode (per D6). Same-tab can't double-click. Cross-tab/cross-user is now also covered by the backend Redis flag.

## D8. Concurrency guard — Redis flag + downloaded-union 409

The admin endpoint must reject **two** races:
1. **Already-downloaded:** mode is in the union of `available_modes` across worker heartbeats. Easy — read state, check union.
2. **Already-downloading:** another arq job is currently downloading the same mode. **The PG `Job` table has no `args` column** (verified — `Job` model in [db/models.py:238](../src/songmaker_cli/db/models.py#L238) only stores type/status/progress/error/user_id/heartbeat fields; the `mode` argument lives in the arq Redis queue, not PG). So we can't SQL-filter active jobs by mode. The clean primitive is a **Redis flag** that the arq job sets at start and clears at end.

### New helpers in `acestep_state.py`

```python
DOWNLOAD_KEY_PREFIX = "songmaker:acestep:download"
DOWNLOAD_TTL_SECONDS = 1800  # 30 minutes — longest expected XL download


def download_key(mode: str) -> str:
    return f"{DOWNLOAD_KEY_PREFIX}:{mode}"


async def set_download_in_progress(pool: ArqRedis, mode: str, job_id: str) -> None:
    await pool.set(download_key(mode), job_id, ex=DOWNLOAD_TTL_SECONDS)


async def clear_download_in_progress(pool: ArqRedis, mode: str) -> None:
    await pool.delete(download_key(mode))


async def read_download_in_progress(pool: ArqRedis, mode: str) -> str | None:
    raw = await pool.get(download_key(mode))
    if raw is None:
        return None
    return raw.decode() if isinstance(raw, bytes) else str(raw)
```

The arq job sets the flag at start (D3 above shows the wiring inside a `try/finally` so it's cleared on success, failure, *and* exception). The TTL is the safety net: if the arq worker is killed mid-download without cleanup, the flag expires after 30 minutes — second attempt is then allowed. 30 minutes is the worst-case xl-base download on a slow connection; tune later if needed.

**Why Redis and not a new DB column:** adding `args` or `mode` to the `Job` table requires a schema migration, alembic, downtime, and now every job type has to populate it. Redis is cheap, ephemeral, perfectly suited to "is this in progress right now". Same primitive shape as the existing `songmaker:acestep:queue:*` keys.

**Why not a per-mode lock in `acestep_worker/downloads.py`:** that's worker-side, and Phase 5 explicitly avoids touching worker code (see "Files NOT touched"). The Redis flag lives in the control plane where it belongs.

### The admin endpoint check

```python
# inside download_model_endpoint, after the no-online-workers check
downloaded_union: set[str] = set()
for w in workers:
    state = await read_worker_state(pool, w.id)
    if state is not None:
        downloaded_union.update(state.get("available_modes", []))
if mode in downloaded_union:
    raise HTTPException(409, f"Model '{mode}' is already downloaded")

in_progress_job = await read_download_in_progress(pool, mode)
if in_progress_job is not None:
    raise HTTPException(
        409,
        f"Model '{mode}' is already being downloaded (job {in_progress_job})",
    )
```

Both checks fail-open after the TTL expires — if the original arq job is genuinely dead, the next click works.

### Tests

- `test_download_endpoint_rejects_already_downloaded` — worker state with `available_modes=["sft"]`, POST `/admin/registry/sft/download` → 409.
- `test_download_endpoint_rejects_in_progress` — set the Redis flag for `xl-base`, POST `/admin/registry/xl-base/download` → 409 with the existing job_id in the message.
- `test_download_endpoint_allows_after_flag_expires` — set the flag with a 0.1s TTL via `pool.set(..., ex=0)` (or `delete` directly), confirm subsequent POST passes.
- `test_set_clear_read_download_in_progress` — direct unit tests on the new acestep_state helpers using fakeredis.
- `test_download_arq_job_clears_flag_on_success`, `test_download_arq_job_clears_flag_on_failure`, `test_download_arq_job_clears_flag_on_exception` — three tests for the `try/finally` cleanup, mocking the SSE consumer to return/raise.

### Heartbeat contract — unchanged

The Redis flag uses a separate key namespace (`songmaker:acestep:download:*`) and is **not** part of the worker heartbeat payload. So `tests/test_acestep_state.py::test_heartbeat_payload_keys_match_admin_reader` does not need extending. **Phase 5 does not add any new heartbeat fields** — `available_modes` is already published by Phase 1 and Phase 5 just consumes it. If a future change does add a heartbeat field, that contract test must be extended.

## D9. Files Touched (Phase 5)

| File | Change |
|---|---|
| `src/songmaker_cli/scheduler.py` | Extract `_iterate_task_events` async generator. Add `from collections.abc import AsyncIterator` import. Refactor `consume_task_stream` to use the generator. Add `consume_download_task_stream` and `DownloadTaskResultDTO`. Add `pick_any_online_worker`. |
| `src/songmaker_cli/acestep_state.py` | Add `DOWNLOAD_KEY_PREFIX`, `DOWNLOAD_TTL_SECONDS`, `download_key`, `set_download_in_progress`, `clear_download_in_progress`, `read_download_in_progress` (D8). |
| `src/songmaker_cli/jobs.py` | Add `download_model_on_worker(ctx, job_id, mode)` arq job with Redis-flag try/finally + per-event heartbeat. |
| `src/songmaker_cli/music_worker.py` | Register `download_model_on_worker` in `MusicWorkerSettings.functions` (list literal append). |
| `src/songmaker_cli/admin_api.py` | Add `POST /admin/registry/{mode}/download` endpoint with mode validation (400), no-workers check (503), already-downloaded check (409), already-downloading check (409 via Redis flag). |
| `tests/test_acestep_state.py` | Add tests for the four new download-flag helpers + extend the existing prefix-sync test if needed. |
| `tests/test_scheduler.py` | Tests for `_iterate_task_events`, `consume_download_task_stream`, `pick_any_online_worker`, `DownloadTaskResultDTO`. Verify existing `consume_task_stream` tests still pass after the refactor. |
| `tests/test_jobs.py` | Tests for `download_model_on_worker`: happy path, unknown mode, no online workers, worker unreachable, worker 4xx, SSE error event, SSE done with valid result, SSE done with invalid result, transport drop. |
| `tests/test_admin_api.py` | Tests for the new endpoint: enqueues, validates mode, rejects no workers, rejects already-downloaded (409), requires admin (403). |
| `tests/test_music_worker.py` | Bump `test_music_worker_settings_functions` expected count from 2 → 3, expect `download_model_on_worker` in the tuple. |
| `frontend/src/lib/api/admin.ts` | Add `downloadModel(mode)`. |
| `frontend/src/lib/api/client.ts` | Re-export `downloadModel`. |
| `frontend/src/lib/api/admin.test.ts` | Test for `downloadModel`. |
| `frontend/src/lib/components/ModelRegistryPanel.svelte` | Wire Download button: handler, busy/active state, progress display from `activeJobs`, race-fix-style `$effect` for refresh on disappearance. |
| `docs/acestep.md` | Add a short paragraph on the download UI flow + mention `scripts/download_models.sh` as the bootstrap escape hatch. |

**Files NOT touched:**
- `src/acestep_worker/downloads.py` — already complete from Phase 1.
- `src/acestep_worker/wrapper.py` — `/download_model` endpoint already wired. **Avoiding this file also de-risks conflict with the in-flight model_cache.py heartbeat fix from the parallel agent.**
- `src/acestep_worker/models.py` — `DownloadModelRequest` already defined.
- `src/acestep_worker/task_store.py` — supports `kind="download"` already.
- `tests/acestep_worker/test_downloads.py` — already comprehensive.
- `scripts/download_models.sh` — stays as the CLI escape hatch (parent plan says so).
- `docker-compose.yml`, `docker/acestep-worker.Dockerfile` — `HF_TOKEN` and `HF_HUB_DISABLE_XET=1` are already set.
- Phase 6 / Phase 7 / Phase 8 plan files — not Phase 5's territory.

## D10. Implementation order

Strict order. Each step leaves the tree compiling and the tests passing for the parts that aren't yet rewritten. **Three hard checkpoints** are marked HARD — do not skip them. They exist because the refactor in step 3 must not regress existing scheduler tests, and the heartbeat call in step 7 is the difference between "long download works" and "the stale-job reaper kills it after 5 minutes".

1. **Read CLAUDE.md and this sub-plan one more time** (1 min)
2. **Confirm no parallel agent work conflicts.** The heartbeat-race agent has landed (`c32b246` + `c5a11e0`); the sharded-shard fix has landed (`b5a984d`). Phase 5 touches none of the files those changes touched. Verify with `git log --oneline -10` then `git status` (should be clean). (1 min)
3. **`scheduler.py` refactor only** — extract `_iterate_task_events` async generator (D1). Rewrite `consume_task_stream` as a thin wrapper around it. Add `from collections.abc import AsyncIterator` to the existing imports. **Do NOT add download code yet, do NOT add the new picker, do NOT touch `jobs.py`.** (30 min)
4. **HARD checkpoint #1:** `unset VIRTUAL_ENV && uv run pytest tests/test_scheduler.py -q`. **Every existing test must pass.** If anything fails, fix the refactor. Do not proceed until green. The existing tests are the regression net for the refactor — if they're not green, the refactor is wrong, and piling more code on top makes it worse. (5 min — if green; otherwise as long as it takes to fix)
5. **`scheduler.py` add download primitives** — `DownloadTaskResultDTO`, `consume_download_task_stream`, `pick_any_online_worker`. All in scheduler.py. No file moves. (20 min)
6. **`tests/test_scheduler.py` add new tests** per D11 — `_iterate_task_events`, `consume_download_task_stream`, `pick_any_online_worker`. Aim 100% on new code. Run `pytest tests/test_scheduler.py -q` again — both old and new tests must pass. (60 min)
7. **`acestep_state.py` add Redis-flag helpers** — `download_key`, `set_download_in_progress`, `clear_download_in_progress`, `read_download_in_progress`, `DOWNLOAD_KEY_PREFIX`, `DOWNLOAD_TTL_SECONDS`. Per D8. (10 min)
8. **`tests/test_acestep_state.py` add helper tests** — set/get/clear, TTL respected, idempotent clear. Use fakeredis. (15 min)
9. **`jobs.py` add `download_model_on_worker`** arq job per D3. **HARD requirement: the `_on_progress` callback MUST call `_touch_heartbeat(factory, job_id)` on every event** (the spec in D3 already does this; do not "simplify" it away). The `try/finally` for the Redis flag is also non-negotiable — without it the flag leaks and the next click is rejected. (40 min)
10. **`music_worker.py` register the new job** in `MusicWorkerSettings.functions` (list literal, append `download_model_on_worker`). (1 min)
11. **`tests/test_jobs.py` add download_model_on_worker tests** — every entry in D14's failure-mode table that maps to an arq-job-side failure should have a test. ~9 tests total. (90 min)
12. **`tests/test_music_worker.py` update** `test_music_worker_settings_functions` — bump count from 2 to 3, assert `download_model_on_worker` is in the list. (5 min)
13. **`admin_api.py` add `POST /registry/{mode}/download`** endpoint per D5 + D8 — mode validation (400), no-workers check (503), already-downloaded check (409), already-downloading check (409), enqueue, return JobResponse. (20 min)
14. **`tests/test_admin_api.py` add endpoint tests** — happy path, all four rejection paths from the failure table (#1, #2, #3, #4), admin-required (403). ~6 tests. (40 min)
15. **HARD checkpoint #2:** `unset VIRTUAL_ENV && uv run ruff check src/ tests/` and `pytest tests/test_scheduler.py tests/test_jobs.py tests/test_admin_api.py tests/test_music_worker.py tests/test_acestep_state.py -q`. All green. (5 min)
16. **`frontend/src/lib/api/admin.ts`** add `downloadModel(mode)` per D6. **`client.ts`** re-export. (5 min)
17. **`frontend/src/lib/api/admin.test.ts`** add the one test. `pnpm test admin.test.ts`. (10 min)
18. **`frontend/src/lib/components/ModelRegistryPanel.svelte`** wire the Download button — handler, derived `downloadingByMode`, race-fix `$effect` (**plain `let`, NOT `$state`** — see watchpoint 6), progress display. (40 min)
19. **`docs/acestep.md`** add a single paragraph on the download UI flow + reference `scripts/download_models.sh` as the bootstrap escape hatch. (10 min)
20. **HARD checkpoint #3:** full check sweep:
    - `unset VIRTUAL_ENV && uv run ruff check src/ tests/`
    - `unset VIRTUAL_ENV && uv run pytest tests/ -n auto -q --ignore=tests/test_scorers.py --ignore=tests/test_scorers_extended.py`
    - Frontend: `cd frontend && pnpm check && pnpm lint && pnpm test`
    - Coverage: `--cov=songmaker_cli.scheduler --cov=songmaker_cli.jobs --cov=songmaker_cli.acestep_state --cov-report=term-missing`. 100% on new functions.
    All green before commit. (20 min)
21. **Self-review pass** — `git diff HEAD~N` end-to-end, read every diff. (20 min)
22. **Commit + push** in 2 commits per D16. (5 min)
23. **Smoke test** is the user's job per the established Phase 3/4 convention. Brief them, wait for go.

Total wall clock: ~7 hours. (Slightly more than the original 6 because of the Redis-flag helpers + concurrency tests.)

## D11. Test strategy

### Critical tests (catch the most bugs)

1. **`test_iterate_task_events_yields_in_order`** — feed a fake httpx response with three SSE chunks (progress, progress, done), assert the generator yields them in the right order with the right tuple shape.

2. **`test_iterate_task_events_stops_after_done`** — yields a `done` event, then more chunks; assert the generator returns and does not yield the trailing chunks.

3. **`test_iterate_task_events_stops_after_error`** — same but with `error`.

4. **`test_iterate_task_events_reconnect_on_transport_drop`** — first stream raises `httpx.TransportError`, second yields `done`. Assert the iterator yields the `done` event from the second attempt.

5. **`test_iterate_task_events_max_reconnects_exhausted`** — all attempts fail. Iterator raises the underlying httpx error.

6. **`test_consume_download_task_stream_done`** — feed a `done` event with `{"result": {"mode": "sft", "size_bytes": 12345}}`. Returns `DownloadTaskResultDTO(mode="sft", size_bytes=12345)`.

7. **`test_consume_download_task_stream_error`** — feed an `error` event. Raises `WorkerTaskFailed`.

8. **`test_consume_download_task_stream_invalid_payload_raises`** — `done` event with `{"result": {"mode": "sft"}}` (missing size_bytes). Raises `WorkerTaskFailed` with a clear validation message.

9. **`test_consume_download_task_stream_progress_calls_callback`** — three progress events, callback called with floats.

10. **Existing `test_consume_task_stream_*` tests still pass after refactor** (no new tests, just verify they don't break).

11. **`test_pick_any_online_worker_returns_lowest_id`** — three workers with ids `b`, `a`, `c` all online. Returns `a`.

12. **`test_pick_any_online_worker_no_workers_raises`** — empty PG. `NoCapacityError`.

13. **`test_download_model_on_worker_happy_path`** — mock httpx + scheduler functions. Job transitions queued → running → completed with progress=1.0.

14. **`test_download_model_on_worker_unknown_mode`** — Pre-set job to queued, call with `mode="ghost"`, assert job ends up failed with `error_type="invalid_mode"`.

15. **`test_download_model_on_worker_no_online_workers`** — `pick_any_online_worker` raises `NoCapacityError`. Job ends up failed with `error_type="no_workers"`.

16. **`test_download_model_on_worker_worker_unreachable`** — httpx raises `ConnectError` on `/download_model` POST. Job failed with `error_type="worker_unreachable"`.

17. **`test_download_model_on_worker_worker_returns_500`** — POST returns 500. Job failed with `error_type="worker_error"`.

18. **`test_download_model_on_worker_sse_error_event`** — POST OK, but SSE yields an `error` event. Job failed with `error_type="download_error"`.

19. **`test_download_model_on_worker_progress_writes_to_db`** — POST OK, SSE yields progress events at 0.25, 0.50, 0.75, then `done`. Assert `_update_job` was called with each progress fraction, then completed.

20. **`test_download_endpoint_unknown_mode`** — POST `/admin/registry/ghost/download`. 400.

21. **`test_download_endpoint_no_workers`** — empty PG. 503.

22. **`test_download_endpoint_already_downloaded`** — worker state has `available_modes=["sft"]`. POST `/admin/registry/sft/download`. 409.

23. **`test_download_endpoint_enqueues_job`** — happy path. Assert `Job` row created with type `download_model_on_worker`, returned `JobResponse` has the right shape, queue position is set.

24. **`test_download_endpoint_requires_admin`** — non-admin session. 403. (May already be covered by the route-level `Depends(require_admin)` check in admin tests.)

25. **`test_music_worker_settings_functions_includes_download_model`** — assert `download_model_on_worker` is in `WorkerSettings.functions`.

26. **Frontend `downloadModel POSTs to registry endpoint`** — already specified in D6.

### Tests to avoid

- ❌ Mocking `consume_download_task_stream` and asserting it was called from `download_model_on_worker` (tests the test, not the impl).
- ❌ Mocking `pick_any_online_worker` and asserting the order — test the picker directly with real fakeredis.
- ❌ Asserting on the exact `_update_job` call count without checking its arguments — count alone doesn't catch arg-shape regressions.

### Coverage expectation

- 100% on `consume_download_task_stream`, `_iterate_task_events`, `pick_any_online_worker`, `DownloadTaskResultDTO` (new code in `scheduler.py`)
- 100% on `download_model_on_worker` in `jobs.py`
- 100% on `download_model_endpoint` in `admin_api.py`
- 100% on the new `downloadModel` API client function

## D12. Self-review checklist (before commit)

1. **Re-read every changed file via `git diff HEAD~N`**. No skipping.
2. **`grep -rn TODO\\|FIXME\\|XXX src/songmaker_cli/scheduler.py src/songmaker_cli/jobs.py src/songmaker_cli/admin_api.py frontend/src/lib/components/ModelRegistryPanel.svelte`** — zero hits.
3. **No comments in new TS/Python code** (per `feedback_code_standards.md`).
4. **No hardcoded strings reused across files** — `DOWNLOAD_JOB_TYPE = 'download_model_on_worker'` extracted as a TS const, the Python side uses the same string but it's defined once at the arq function name.
5. **`consume_task_stream` regression check** — every existing test in `tests/test_scheduler.py` for `consume_task_stream` and `dispatch_generation` passes after the refactor.
6. **`_iterate_task_events` cleanly handles the "stream ends with no done/error" edge case** — the wrappers raise `WorkerTaskFailed("SSE stream ended without done/error event")` rather than returning silently.
7. **The admin endpoint commits to PG before enqueueing** — same pattern as `load_model_on_worker_endpoint`.
8. **`download_model_on_worker` calls `_touch_heartbeat` on every SSE event** — otherwise the stale-job reaper might kill it (downloads can take 10+ minutes for xl-base on slow connections).
9. **The frontend `$effect` on `activeJobs`** uses `let trackedDownloadJobIds = new Set<string>()`, **NOT** `$state(...)`. This was the critical Phase 4 review finding — don't repeat it.
10. **`pnpm check` passes, `pnpm lint` passes, `pnpm test` passes (full frontend suite).**
11. **`unset VIRTUAL_ENV && uv run ruff check src/ tests/` passes.**
12. **Full backend test suite passes** (excluding scoring tests which need GPU extras).
13. **Coverage 100% on new functions per D11.**
14. **`docs/acestep.md`** download UI paragraph is accurate to what shipped.

## D13. Things to watch out for

### Watchpoint 1: The `_iterate_task_events` refactor regresses scheduler tests

The biggest risk in Phase 5. `consume_task_stream` has ~5 critical scheduler tests already. Run `pytest tests/test_scheduler.py -q` after the refactor and BEFORE adding any download code. If anything fails, fix it before proceeding. The wrapper shape change is small but easy to get wrong (e.g., the `await _maybe_invoke(on_heartbeat)` was previously called for every iteration even before classifying the event — make sure that's preserved).

### Watchpoint 2: `await _maybe_invoke(on_heartbeat)` placement

In the original `consume_task_stream`, heartbeat is called for every event including `done`/`error`. The refactored version must preserve this — the wrapper needs to call `on_heartbeat` *before* deciding whether to return on `done`/`error`. Easy to miss.

### Watchpoint 3: HF `snapshot_download` is blocking and slow

`run_download` (already in Phase 1) wraps it in `asyncio.to_thread`. The download takes 1-15 minutes depending on bandwidth and model size. The arq job timeout (`load_model_on_worker` uses 300s) is too short for a real xl-base download on a slow connection. **Use a much higher timeout** for the SSE stream (and document it). The `DispatchOptions.sse_read_timeout_seconds` defaults to `None` (no read timeout), which is correct — we just need to ensure the OUTER httpx client used for `POST /download_model` (in `download_model_on_worker`) has a 30s timeout for the *submit* call but the SSE consumer has no read timeout. The `_iterate_task_events` uses `options.sse_read_timeout_seconds` which defaults to `None`. ✓

### Watchpoint 4: Job heartbeat reaper killing in-flight downloads

Long downloads (>5 minutes) risk the stale-job reaper killing them. The reaper looks at `Job.last_heartbeat_at`. The arq job needs to call `_touch_heartbeat` on every SSE event (which fires every 2s during a download via `_poll_progress`). Verified the call is in the spec above. **Don't drop it during implementation.**

### Watchpoint 5: HF token presence

`hf_snapshot_download` reads `HF_TOKEN` from env. If unset, downloads will fail at runtime with a 401 from huggingface_hub. The acestep-worker container has `HF_TOKEN` injected from `${HF_TOKEN:-}` in `docker-compose.yml:141`, which falls back to empty string if the host doesn't export it. **Document this in the smoke test instructions:** "ensure `HF_TOKEN=...` is exported in your shell before `docker compose up --build`."

### Watchpoint 6: Frontend race-fix for the `$effect`

Phase 4 critical review finding: the `$effect` that watches activeJobs for disappeared jobs must use `let trackedDownloadJobIds = new Set<string>()`, NOT `$state(new Set<string>())`. The `$state`-wrapped Set assigned with `=` triggers the effect to re-run, which causes `effect_update_depth_exceeded`. **Same trap, same fix.** Reference [WorkerPoolPanel.svelte:28](../frontend/src/lib/components/WorkerPoolPanel.svelte#L28) for the correct pattern.

### Watchpoint 7: Downloaded model doesn't appear in `available_modes` until next heartbeat

After the download completes, the worker's heartbeat publishes `available_modes` every 5 seconds. The registry panel polls every 5 seconds. So worst case there's a ~10s lag between "Downloading… 100%" disappearing and the row flipping to ✓ downloaded. The `$effect`-driven `store.refresh()` from D6 covers part of this (frontend forces a registry poll the moment activeJobs loses the job), but the worker still needs its next heartbeat to publish the new `available_modes`. Acceptable lag — document in smoke test.

### Watchpoint 8: Concurrent downloads for same mode (deferred per D7)

Add a watchpoint to the smoke test instructions: **don't click Download twice on the same row**. Single-user platform, single-tab, this won't happen organically.

### Watchpoint 9: SSE empty stream edge case

If the worker accepts `/download_model` but `start_download` somehow fails to spawn the background task (or it crashes immediately), `/tasks/{task_id}/stream` will yield no events and close. `_iterate_task_events` will return without yielding. The wrappers handle this by raising `WorkerTaskFailed("SSE stream ended without done/error event")`. **Test this case explicitly** in `test_consume_download_task_stream_empty_stream_raises`.

### Watchpoint 10: The `tests/test_admin_api.py` arq pool override

The Phase 2 admin tests use `app.dependency_overrides[get_arq_pool_dep] = lambda: fakeredis_instance` (per Phase 2 sub-plan D11). New download endpoint tests follow the same pattern — don't try to mock at the `arq_pool.get_arq_pool()` import level, override the FastAPI dependency.

### Watchpoint 11: `arq_pool.get_arq_pool()` is the FastAPI-side singleton

The admin endpoint enqueues via `get_arq_pool()` (NOT `get_arq_pool_dep`). The `_dep` wrapper exists for FastAPI dependency injection in **read** paths. Enqueue paths use the singleton directly to keep the call site simple. This matches `load_model_on_worker_endpoint`'s pattern. Don't refactor it — that's a separate concern.

### Watchpoint 12a: Disk space — XL models are ~13 GB each

`xl-base`, `xl-sft`, `xl-turbo` are each ~13 GB. Downloading all three fills ~40 GB of the `_models/acestep/checkpoints/` host volume mount. Phase 5 does not enforce a disk-space check (out of scope), but the smoke test (D17) should:
- `df -h _models/acestep/` before clicking Download
- Confirm there's headroom for the model being downloaded
- After completion, `du -sh _models/acestep/checkpoints/acestep-v15-xl-base/` to verify the actual size

If the disk fills mid-download, the worker emits an `error` SSE event (failure mode #15 in D14) and the partial files stay on disk. The next attempt's `is_model_downloaded` check (post-`b5a984d`, shard-aware) correctly reports "not downloaded" and the retry resumes via HF cache.

### Watchpoint 12b: HF_TOKEN must be set for gated models

ACE-Step models on HF may be gated (require accepting a license + an `HF_TOKEN` with the right access). The acestep-worker container reads `HF_TOKEN` from env. **The smoke test must verify `echo $HF_TOKEN` is non-empty in the host shell before `docker compose up`.** If the token is missing, the download fails with a 401 → worker emits `error` SSE → arq job fails with `error_type=download_error` and a clear message. The implementer should ensure the failure message includes "HF_TOKEN" so the operator knows what to fix (the worker's exception message will already include this since `huggingface_hub` raises `HfHubHTTPError` with the URL).

### Watchpoint 13: Mode encoding in URL

`encodeURIComponent(mode)` on the frontend, and the FastAPI path-param decoder on the backend. The mode names are `sft`, `turbo`, `xl-sft`, `xl-turbo`, `xl-base` — none have URL-special characters today, but `xl-base` has a hyphen which is fine. Just don't bypass the encoding helper "because the modes look safe".

## D14. Failure-mode enumeration

The download path crosses three trust boundaries (admin → arq queue → music-worker → acestep-worker → HF) and Phase 5 must handle each failure mode explicitly. This is the canonical list — implementer should ensure every entry maps to a test in D11.

| # | Failure | Where it fires | Job ends as | error_type |
|---|---|---|---|---|
| 1 | Unknown mode (typo, hostile input) | admin endpoint pre-check | rejected at endpoint with 400 | n/a (no job created) |
| 2 | No online workers | admin endpoint pre-check | rejected at endpoint with 503 | n/a (no job created) |
| 3 | Already downloaded (heartbeat union) | admin endpoint | rejected at endpoint with 409 | n/a (no job created) |
| 4 | Already downloading (Redis flag) | admin endpoint | rejected at endpoint with 409 | n/a (no job created) |
| 5 | Arq queue unavailable | admin endpoint enqueue | rejected at endpoint with 503 | job marked failed before raising |
| 6 | Worker unreachable on `POST /download_model` | arq job, httpx submit step | failed | `worker_unreachable` |
| 7 | Worker returns 4xx on `POST /download_model` | arq job, status check | failed | `worker_error` |
| 8 | SSE transport drop, exhausted reconnects | arq job, `_iterate_task_events` raises | failed | `sse_transport` |
| 9 | Worker emits `error` SSE event (HF auth fail, disk full, network drop, generic exception) | arq job, `WorkerTaskFailed` raised by wrapper | failed | `download_error` |
| 10 | `done` event with malformed result payload | arq job, `WorkerTaskFailed` from `DownloadTaskResultDTO.model_validate` | failed | `download_error` |
| 11 | SSE stream ends without done/error | arq job, wrapper raises `WorkerTaskFailed("SSE stream ended without done/error event")` | failed | `download_error` |
| 12 | Music-worker process killed mid-download (SIGKILL, OOM) | nowhere — the in-progress job sits as "running" until the stale-job reaper notices | failed (eventually) | reaped via existing stale-job reaper; Redis flag clears via TTL after 30 min |
| 13 | HF rate limit (429) | arq job — `consume_download_task_stream` sees an `error` event from the worker | failed | `download_error` (no auto-retry in Phase 5; admin retries manually) |
| 14 | HF auth failure (HF_TOKEN missing/invalid) | arq job — same as #13, error event from worker | failed | `download_error` (clear message: "401 from huggingface_hub, check HF_TOKEN env var") |
| 15 | Disk full mid-download | arq job — same as #13 | failed | `download_error` (next attempt cleans up via the existing `is_model_downloaded` shard check from b5a984d, which now treats partial sharded layouts as not-downloaded) |

**Auto-retry is NOT in Phase 5.** The parent plan mentions "3 attempts via the admin endpoint" — that's deferred to Phase 6. For Phase 5, every failure path produces a clear error message in the PG `Job` row, the frontend toast surfaces it, and the admin manually clicks Download again. The Redis flag (D8) prevents the admin's retry from racing with a still-cleaning-up failed attempt.

**Recovery from partial downloads (#15) is automatic** thanks to two pre-existing pieces:
- HF `snapshot_download` resumes from cache (uses content hashes, skips already-correct files)
- `is_model_downloaded` (post-`b5a984d`) requires the full sharded layout to be present, so a partial download is treated as not-downloaded and the retry resumes

The implementer should verify recovery works in the smoke test (D17), but does not need to write code for it.

## D15. What is NOT in Phase 5 (deferred)

- **Per-mode download lock** to prevent concurrent downloads of the same mode → Phase 6 (D7)
- **Download cancellation** (the user clicks Download then changes their mind) → Phase 6 if needed; today the job runs to completion
- **Download retry** (parent plan mentions "3 attempts via the admin endpoint") → Phase 6 if HF flakiness becomes a real problem; for now a single attempt with a clear error is enough
- **Visual progress bar element** instead of percentage text → Phase 6 polish if it feels lacking
- **Multi-host volume sync** (worker A downloads, worker B doesn't see it) → out of scope; current architecture is shared host volume
- **Worker startup auto-download of missing models** → not in scope; admin must trigger explicitly or use `scripts/download_models.sh` for bootstrap

If you find yourself implementing any of these in Phase 5, **stop**.

## D16. Branching + commits

Phase 5 commits go on `feat/acestep-worker-pool`. Suggested 2-commit split:

1. **Backend** — `scheduler.py` refactor + new primitives, `jobs.py` arq job, `music_worker.py` registration, `admin_api.py` endpoint, all backend tests, `docs/acestep.md`. Self-contained: backend tests pass before touching the frontend.
2. **Frontend** — `admin.ts` + `client.ts` re-export, `admin.test.ts` test, `ModelRegistryPanel.svelte` wire-up.

Or one big commit if the splits feel artificial. Per `feedback_speed.md`, **two commits is the recommended ceiling** — don't fragment further.

Push to `origin/feat/acestep-worker-pool` after the second commit.

## D17. Smoke test (manual, after implementation)

The user has the real GPU + the full stack. Smoke test:

1. **Pre-flight:** ensure `HF_TOKEN=...` is exported. `docker compose ps` shows `acestep-worker-0` healthy. The Model Registry panel shows `xl-base` as `✗ not downloaded`.
2. `timeout 300 docker compose up -d --build --wait songmaker-music-worker songmaker-web` — backend changes need both rebuilt. Frontend changes need `songmaker-web` rebuilt (Phase 4 lesson).
3. Hard-refresh the browser. Open `/settings/users` → ACE-Step tab as admin.
4. Click **Download** on the `xl-base` row.
5. Within ~3s the row should show `Downloading… 0%`.
6. Progress should advance every ~2s (worker poll interval). For xl-base on a fast connection, expect ~3-5 minutes total. On a slow connection, 10-20 minutes.
7. During download, open DevTools → Network → confirm `/api/admin/workers` and `/api/admin/registry` are still polling (the SSE for the job is on `/api/jobs/{id}/stream`).
8. Switch tabs (so `document.hidden === true`). Confirm the download keeps running (it's server-side; the frontend pause only affects polling).
9. Switch back. Confirm the progress display picks up where it should (the `EventSource` is still open, `activeJobs` is still tracking).
10. On completion, the progress text disappears. Within ~10s, the row flips to `✓ downloaded`.
11. The Worker Pool panel's Load model dropdown for `acestep-worker-0` should now offer `xl-base` as a selectable option (it was already in `availableModes` — verify).
12. Click Load → xl-base. Confirm it loads (~30-90s). Card status flips to `Idle` with `Loaded: xl-base`.
13. **Failure mode test:** with a model already downloaded, click Download on it directly via the API: `curl -X POST -b session.cookie http://localhost:8080/api/admin/registry/sft/download` — expect 409 `Model 'sft' is already downloaded`.
14. **Cleanup:** the new `xl-base` files live in `_models/acestep/checkpoints/acestep-v15-xl-base/`. Verify with `ls`. `du -sh` to confirm ~12 GB. Don't delete unless you actually want to re-download.

If any step fails, **fix before committing.** The unit tests are not enough on their own — the integration is what the smoke test catches.

## D18. Quick context for next session's first message

If you're a new agent picking this up: read `CLAUDE.md`, then [acestep-worker-pool.md](acestep-worker-pool.md), then this file. Phase 1 = `c416194`, Phase 2 = `275518c`, Phase 3 = `74b8576`, Phase 4 = `aca35f6`, plus `cf1fa5d` (heartbeat field-name fix) and the in-flight model_cache heartbeat-race agent commit. Branch is `feat/acestep-worker-pool`.

The biggest single risk in Phase 5 is the **`consume_task_stream` refactor** (D1, watchpoints 1+2). The existing scheduler tests are the safety net — run them after the refactor and BEFORE adding any download code. Everything else mechanically follows.

The second-biggest risk is **repeating the Phase 4 `$effect`-self-write bug** (watchpoint 6). The race-fix `$effect` for tracking disappeared download jobs MUST use a plain `let`, not `$state`.

The third-biggest risk is **the parent plan's scope drift around Phase 5** — it describes the worker-side `downloads.py` as a stub that needs implementing. **It's already done.** Phase 5 is web-side + frontend wiring only on the implementation axis.
