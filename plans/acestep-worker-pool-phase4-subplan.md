# Phase 4 Sub-plan — Admin UI rewrite (Worker Pool + Model Registry)

> Concrete implementation plan for Phase 4 of [acestep-worker-pool.md](acestep-worker-pool.md). Phase 4 is **frontend-only**: the backend endpoints (`/api/admin/workers`, `/api/admin/registry`, `/api/admin/workers/{id}/load_model`, `/api/admin/workers/{id}/evict_model`) shipped in Phases 2–3. This phase consumes them and replaces the empty ACE-Step admin tab with two new panels. Read end-to-end before starting; this captures decisions that aren't in the parent plan.

## State at start of Phase 4

- **Branch:** `feat/acestep-worker-pool` (Phase 1 = `c416194`, Phase 2 = `275518c`, Phase 3 = `74b8576` + follow-ups `ea9f099`, `c20a6d9`, plus phase-7/8 docs `69787ec`/`de4ea8e`)
- **Backend (already shipped):**
  - `GET /api/admin/workers` → `WorkerPoolResponse { workers: WorkerInfo[] }` joining PG identity + Redis ephemeral state
  - `GET /api/admin/registry` → `RegistryResponse { models: RegistryModelResponse[] }` (per-mode union of `available_modes` across workers, plus `loaded_on`/`loading_on`)
  - `POST /api/admin/workers/{id}/load_model` → returns `JobResponse` (arq job; admin SSE-subscribes via existing `/api/jobs/{id}/stream`)
  - `POST /api/admin/workers/{id}/evict_model` → synchronous proxy, returns `StatusResponse`
  - All four require `Depends(require_admin)` → 403 for non-admin sessions
- **Restart endpoint** is **not** shipped — it's deferred to Phase 6 per parent plan. Phase 4's "Restart" button will be a stub disabled with a tooltip, **or** omitted from the card entirely (decision in D2).
- **`download_model_on_worker`** is **not** shipped — Phase 5. The "Download" button on the Model Registry rows is a stub disabled with "Coming in Phase 5", **or** omitted (decision in D5).
- **Frontend admin tab** [frontend/src/routes/settings/users/+page.svelte:828-834](../frontend/src/routes/settings/users/+page.svelte#L828-L834) currently has a placeholder section under the existing `tab === 'acestep'` branch:
  ```svelte
  <section>
      <h2>ACE-Step Workers</h2>
      <p class="hint">
          Worker pool monitoring and model management UI is coming in Phase 4. Use the
          backend admin endpoints (/api/admin/workers, /api/admin/registry) for now.
      </p>
  </section>
  ```
  That `<section>` is what Phase 4 replaces.
- **Existing SSE pattern** lives in [frontend/src/lib/stores/jobs.ts](../frontend/src/lib/stores/jobs.ts) — `EventSource` against `/api/jobs/{id}/stream`, error retry up to `MAX_POLL_ERRORS=10`, status terminal-state handling, toast notifications, song refresh on completion. Used today by `trackJob(job, context)` for generation jobs from `GenerationView.svelte`. Tested in [frontend/src/lib/stores/jobs.test.ts](../frontend/src/lib/stores/jobs.test.ts) with a `MockEventSource` that's stubbed via `vi.stubGlobal('EventSource', MockEventSource)`.

## Phase 4 goal (recap)

Replace the empty ACE-Step admin tab content with **two stacked panels**:
1. **Worker Pool** — one card per worker, polled every 3 s, shows identity + Redis state, has Load/Evict actions.
2. **Model Registry** — one row per known mode, shows downloaded/loaded badges, has Download stub button (disabled until Phase 5).

The "Generation Defaults / ACE-Step Available Models" controls (currently under the same tab) are **separate concerns**. This sub-plan keeps them where they are; D8 covers the layout decision.

## Surprise found during exploration (must address)

**`frontend/src/lib/api/types.ts` does NOT contain the worker/registry types yet.** The user's task description says they're already there from Phase 2/3 — they aren't.

Verified by grep: zero matches for `Worker`, `Registry`, `WorkerInfo`, `WorkerPool`, `RegistryModel` in [frontend/src/lib/api/types.ts](../frontend/src/lib/api/types.ts).

The reason: [scripts/generate_types.py](../scripts/generate_types.py) emits a **curated** list (`_EMIT_ORDER`, lines 80–111) and a **curated** rename map (`_RESPONSE_MODEL_NAMES`, lines 39–69). Neither was updated in Phases 2 or 3 when `api_models/workers.py` was added.

**Phase 4 must update both lists** before regenerating, otherwise `pnpm check` fails on the new admin code.

The Pydantic models that need TS counterparts are in [src/songmaker_cli/api_models/workers.py](../src/songmaker_cli/api_models/workers.py):
- `WorkerIdentity` → `WorkerIdentityItem`
- `WorkerEphemeralState` → `WorkerEphemeralStateItem`
- `WorkerInfo` → `WorkerInfoItem` (depends on the two above)
- `WorkerPoolResponse` → `WorkerPoolResponse`
- `RegistryModelResponse` → `RegistryModelItem`
- `RegistryResponse` → `RegistryResponse`

**Not needed in TS:** `WorkerRegisterRequest`/`Response` (internal worker→web only), `LoadModelOnWorkerRequest`/`EvictModelOnWorkerRequest` (the frontend serializes the body inline; mode is a single field).

`WorkerStatus = Literal["online", "loading", "offline"]` already round-trips through the existing `Literal` handling in `_py_type_to_ts` (line 150-152) — verified the generator emits `'online' | 'loading' | 'offline'` for that field.

**Verification:** after editing `_EMIT_ORDER` + `_RESPONSE_MODEL_NAMES`, run `python scripts/generate_types.py` and grep for `WorkerInfoItem` in the regenerated file. If absent, the rename map is wrong.

## D1. File layout — one page-local helper, two new components, one new store, one new client module

The current admin page is one big `+page.svelte` (1284 lines). Adding two more panels inline would push it over 1500 lines and tangle the worker-pool reactive state with the user-management reactive state. **Decision:** extract the two panels into their own components, alongside a small store for polling state. This matches how `GenerationView.svelte` already extracts player UI vs. playlist UI.

| New file | Purpose |
|---|---|
| `frontend/src/lib/api/admin.ts` | Add `listWorkers`, `loadModelOnWorker`, `evictModelOnWorker`, `getRegistry`. The existing file (60 lines) has the user-admin functions; just append. |
| `frontend/src/lib/components/WorkerPoolPanel.svelte` | The Worker Pool panel: polls `/api/admin/workers`, renders one card per worker, owns the Load/Evict button state, dispatches load jobs and tracks them via existing `trackJob`. |
| `frontend/src/lib/components/ModelRegistryPanel.svelte` | The Model Registry panel: polls `/api/admin/registry`, renders one row per mode, has the (Phase 5–stub) Download button. |
| `frontend/src/lib/stores/adminPolling.ts` | Tiny shared utility: `createPollingStore<T>(fetcher, intervalMs)` that handles `document.visibilitychange` (pause when hidden) and exposes `{ data, error, loading, refresh, start, stop }`. Reused by both panels and tested independently. |

**Why a shared polling store rather than duplicating the loop in each component:**
- Both panels poll. Both need the same `document.hidden` pause behavior. Both need the same error-toast-on-403 path.
- One unit-tested helper > two slightly different copies.
- It's ~50 LOC. Not over-abstraction.

The two panels are then mounted from `+page.svelte` inside the `tab === 'acestep'` branch, **above** the existing "Available Models" / "Generation Defaults" sections (D8).

`adminPolling.ts` is intentionally generic over `T` so it can be reused for any admin polling endpoint added later (Phase 6 worker metrics, etc.).

## D2. Worker Pool panel — exact card layout

Match the parent plan's information density. Each worker is a card; the panel shows N cards stacked vertically.

```
┌─ Worker Pool ─────────────────────────────────────────────────┐
│  ● acestep-worker-0          GPU 0  •  24 GB                  │
│    Loaded:  sft (3.4 GB), xl-sft (12 GB)                      │
│    Status:  Idle                                              │
│    Queue:   0 jobs                                            │
│    Last seen: 2s ago                                          │
│    [ Load model ▾ ]  [ Evict sft ]  [ Evict xl-sft ]          │
│                                                                │
│  ⚠ acestep-worker-1          GPU 1  •  24 GB                  │
│    Status:  Loading xl-base… (1m 23s elapsed)                 │
│    Last seen: 4s ago                                          │
│    [ Load model ▾ ]  [ Evict ]   ← all disabled               │
│                                                                │
│  ✗ acestep-worker-2          GPU 2  •  ?                      │
│    Status:  Offline (no heartbeat)                            │
│    Last seen: never                                           │
└────────────────────────────────────────────────────────────────┘
```

**Header line:**
- Status dot — color from `WorkerInfo.status`:
  - `online` → green `●`
  - `loading` → amber `⚠`
  - `offline` → red `✗`
- `identity.id` (the worker name)
- `GPU {identity.gpu_id ?? '?'}` (right-aligned, dim text)
- `{identity.vram_total_gb ?? '?'} GB` (right-aligned, dim text)

**Body lines (only when `state` is non-null):**
- **Loaded:** comma-separated `state.loaded` (pulled from Redis state). If empty, render `Loaded: (none)`.
  - VRAM size per model is **not in the response** — the parent plan's "(12 GB)" annotations are aspirational. **Decision:** omit per-model size for now. Add a Phase 6 follow-up if useful.
- **Status:** derived locally from `state.target_loading` + `state.loaded`:
  - `state.target_loading != null` → `Loading {target_loading}… ({elapsed} elapsed)` where elapsed = `now - state.last_heartbeat_at` is **wrong** (it's heartbeat age, not load duration). The Redis state doesn't carry a `loading_started_at` field. **Decision:** just say `Loading {target_loading}…` without an elapsed counter. Add a `loading_started_at` field to the worker heartbeat in a Phase 6 follow-up if useful.
  - `state.loaded.length > 0 && state.queue_depth > 0` → `Busy ({queue_depth} in queue)`
  - `state.loaded.length > 0 && state.queue_depth === 0` → `Idle`
  - `state.loaded.length === 0` → `No model loaded`
- **Queue:** `{state.queue_depth} jobs`
- **VRAM:** `{state.vram_used_gb}/{state.vram_total_gb} GB` if both are present; omit otherwise. The parent plan didn't list VRAM here but the field exists in the response and it's free to display.
- **Last seen:** humanized delta from `state.last_heartbeat_at` to now. Use the existing `formatRelativeTime` helper from `frontend/src/lib/utils/format.ts` if it exists; otherwise render the raw ISO timestamp. (Verify in implementation; if no helper, write a 5-line one inline rather than a new utils file.)

**Body line (when `state` is null, i.e. `status === 'offline'`):**
- A single line: `Offline (no heartbeat)`. No Loaded/Queue/VRAM rows.

**Action buttons:**
- **Load model ▾** — a `<select>` styled as a button, options drawn from `MODEL_CONFIG_PATHS` (the Python constant). The frontend doesn't import Python — instead, the options are derived from the `Model Registry` panel's data (which is fetched from `/api/admin/registry`, which iterates `MODEL_CONFIG_PATHS` server-side). **Decision:** the Worker Pool panel reads the registry data from a parent-level signal so both panels share one fetch lifecycle. Concretely, `+page.svelte` does the registry poll and passes `availableModes: string[]` as a prop to `WorkerPoolPanel`. Avoids two separate fetches against the same endpoint.
- **Evict {mode}** — one button per loaded model. Calls `evictModelOnWorker(workerId, mode)`. On success, refreshes the polling. On failure, sets `panelError` (toast).
- **Restart** — **omitted in Phase 4**. The endpoint isn't shipped (Phase 6). Adding a button that 404s is worse than omitting the button. **The parent plan's draft ASCII shows `[Restart]`** — that's aspirational; the feature isn't there yet. Document the decision in a code comment (or rather, in the panel docstring at the top of the file — no inline comments per `feedback_code_standards.md`).
- **Pin** — also omitted; same reason. The parent plan says "stub button disabled". One disabled button is fine; two disabled buttons is junk UI. Skip Pin too.

**Disabled state:** when `state.target_loading != null` (loading in progress), all action buttons disabled. When the pending load job is in `activeJobs` for this worker (matched by storing `workerId` on the trackJob context), the Load button shows a spinner.

**Empty state:** when `workers.length === 0`:
> **No workers registered.** Start the `songmaker-acestep-worker-0` container and refresh.

**Error state (network failure on poll):**
- First failure: log to console, keep last-known data on screen, show a small `⚠ Connection lost — retrying…` banner above the cards.
- After 5 consecutive failures: clear the data, show `Cannot reach the worker pool API. Check the server logs.` as the panel-level error.

**403 (admin role lost mid-session):**
- Polling stops, panel shows `Admin access required.` Same wording as the page-level `denied` div. The `apiFetch` helper currently auto-redirects on 401; verify the behavior on 403 and match it. If 403 doesn't auto-redirect, this panel handles it locally.

## D3. Model Registry panel — exact row layout

```
┌─ Model Registry ──────────────────────────────────────────────┐
│  Mode      Status                                  Actions    │
│  ────────  ──────────────────────────────────────  ────────── │
│  sft       ✓ downloaded   loaded ×1                [Download] │
│  turbo     ✓ downloaded   loaded ×0                [Download] │
│  xl-sft    ✓ downloaded   loaded ×1   loading ×0   [Download] │
│  xl-turbo  ✓ downloaded   loaded ×0                [Download] │
│  xl-base   ✗ not downloaded                        [Download] │
└────────────────────────────────────────────────────────────────┘
```

**Per row** (one per `RegistryModelResponse`):
- **Mode:** `model.mode` (e.g. `sft`, `xl-base`)
- **Status badges:**
  - `✓ downloaded` (green) if `model.downloaded === true`, else `✗ not downloaded` (red/dim)
  - `loaded ×{N}` where N = `model.loaded_on.length`. Hide if zero? **Decision:** show always, including `×0`, so the column doesn't jiggle as workers load/evict.
  - `loading ×{N}` where N = `model.loading_on.length`. Hide if zero (it's the rare state).
- **Actions:**
  - **Download** — disabled in Phase 4 (`Phase 5 — coming soon` tooltip). The button stub stays so the layout lands correctly when Phase 5 wires it up.
  - **Toggle `is_active`** — the parent plan mentions "Toggle for `is_active` (gated: cannot enable a non-downloaded model)". **Reality check:** `RegistryModelResponse` doesn't have an `is_active` field. That's a separate concept handled by [admin_api.py:fetchAllModels / toggleModelApi](../src/songmaker_cli/admin_api.py) (the existing "Available Models" section in the same tab). **Decision:** do not duplicate that toggle here. The existing "Available Models" section stays; the Model Registry panel is purely informational + the (stub) Download button.

**Empty state:** never empty — the backend always returns one row per `MODEL_CONFIG_PATHS` entry (5 modes today). If the endpoint returns `{ models: [] }`, that's a backend bug; show `No models in registry.`

**Error state:** same pattern as Worker Pool panel.

## D4. Polling cadence + visibility

**Worker Pool panel:**
- Interval: **3000 ms** (parent plan says 3 s; workers heartbeat every 5 s, so 3 s polling guarantees at most one stale frame visible to the user).
- Pause on `document.visibilitychange` when `document.hidden === true`. Resume immediately on visibility regain (also fires an immediate fetch instead of waiting for the next tick).

**Model Registry panel:**
- Interval: **5000 ms**. Slower than the worker pool because the registry changes much less often (downloads are rare; loaded counts already show up in the Worker Pool panel).
- Same `document.hidden` pause.

**Why both panels poll independently:**
- Decoupled lifecycle: the user can scroll past the Model Registry but still want a fresh Worker Pool.
- Both endpoints are cheap (small JSON) and the load on Redis is negligible.
- Sharing the registry data with the Worker Pool panel for the Load dropdown (D2) is done by passing the latest `availableModes` from `+page.svelte` as a Svelte prop, **not** by sharing a poll loop. The Worker Pool panel doesn't care if the dropdown options lag the registry by 5 s; modes don't appear/disappear at runtime.

**Tab switch handling:**
- The polling stores start when the panel mounts and stop on `onDestroy`. Switching admin tabs (`tab = 'users'`) unmounts the components, which stops the polls. Switching back remounts and restarts. This is the right semantics — no zombie pollers.
- The current admin page does **not** unmount sections when switching tabs (it uses `{#if tab === 'X'}` blocks, which Svelte does unmount/destroy). Verified by reading [+page.svelte:810](../frontend/src/routes/settings/users/+page.svelte#L810) — the `acestep` block is wrapped in `{#if tab === 'acestep'}`, so unmount is automatic.

## D5. Load model progress UI — reuse the existing `trackJob` SSE pipeline

The `POST /api/admin/workers/{id}/load_model` endpoint returns a `JobResponse` (which is `JobItem` on the frontend). The backend creates a real `Job` row, enqueues an arq task, and the existing `/api/jobs/{id}/stream` SSE endpoint streams its status updates. **Don't invent a parallel SSE channel.**

**Flow:**
1. User clicks `Load model` → selects `xl-sft` from the dropdown.
2. `loadModelOnWorker(workerId, 'xl-sft')` POSTs and gets back a `JobItem`.
3. Frontend calls `trackJob(job, { workerId, mode: 'xl-sft' })` from `frontend/src/lib/stores/jobs.ts`.
4. `trackJob` opens an `EventSource('/api/jobs/{id}/stream')` and pushes the job into `activeJobs`.
5. The Worker Pool panel subscribes to `activeJobs` and finds any active job whose context has `workerId === card.identity.id`. While present, the card shows a spinner overlay with `Loading {mode}…` and the action buttons are disabled.
6. On completion, `trackJob` removes the job from `activeJobs` after a small delay; the panel's regular 3 s poll catches up and the card shows the new `loaded` state from the worker's heartbeat.
7. On failure, the user gets the existing toast (`{type} failed: {error}`) and the panel returns to its normal state.

**Required change to `trackJob`:** today the context is typed as `{ songId?: string; genId?: string }`. Phase 4 widens it to `{ songId?: string; genId?: string; workerId?: string; mode?: string }`. Two new optional fields, no behavior change.

**Required change to `refreshSongData`:** the function only runs when `activeJob.songId` is set, so worker-load jobs (which have no `songId`) skip it. Verified by reading [jobs.ts:101-112](../frontend/src/lib/stores/jobs.ts#L101-L112). No code change needed there.

**Expected job duration:** 30–90 s. The existing `MAX_POLL_ERRORS=10` and the SSE keepalive should comfortably handle that; no timeout tuning needed.

**Edge case: server restart mid-load.** The existing pipeline already handles this — the SSE stream emits a `failed` job with `error_type === 'server_restart'` and the toast says "Server restarted — please retry". Verified at [jobs.ts:67-71](../frontend/src/lib/stores/jobs.ts#L67-L71).

**Edge case: user navigates away mid-load.** The Worker Pool panel unmounts. The job continues running on the backend, but `activeJobs` is a global store, so when the user comes back the job is still there and the panel re-renders the spinner. ✓ correct behavior with no extra work.

## D6. Evict — synchronous, no SSE

`POST /api/admin/workers/{id}/evict_model` is synchronous (the worker handles eviction in <1 s). Frontend just `await`s the response, then:
- On success: kick a `refresh()` of the Worker Pool poll to pick up the new state immediately.
- On failure: set a panel-level error banner with the response message.

No job tracking, no spinner overlay (a button-level "..." disabled state for the half-second is enough).

## D7. API client additions ([frontend/src/lib/api/admin.ts](../frontend/src/lib/api/admin.ts))

Append to the existing file. Match the existing function shape exactly — no Promise-fluff wrappers, no try/catch (let `apiFetch` throw and the caller handle).

```typescript
import type {
    WorkerPoolResponse,
    RegistryResponse,
    JobItem,
} from './types';

export async function listWorkers(): Promise<WorkerPoolResponse> {
    return apiFetch<WorkerPoolResponse>('/api/admin/workers');
}

export async function getRegistry(): Promise<RegistryResponse> {
    return apiFetch<RegistryResponse>('/api/admin/registry');
}

export async function loadModelOnWorker(
    workerId: string,
    mode: string,
): Promise<JobItem> {
    return apiFetch<JobItem>(`/api/admin/workers/${workerId}/load_model`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
    });
}

export async function evictModelOnWorker(
    workerId: string,
    mode: string,
): Promise<void> {
    await apiFetch(`/api/admin/workers/${workerId}/evict_model`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
    });
}
```

These are then re-exported from `frontend/src/lib/api/client.ts` if the existing pattern requires it (verify — most admin functions are imported directly from `$lib/api/client` in the page). Match whichever convention the existing admin functions use.

## D8. Where the panels go inside `+page.svelte`

The current `tab === 'acestep'` branch (lines 810–835) contains:
1. `<section><h2>Available Models</h2>` — the model on/off toggles ([lines 811-826](../frontend/src/routes/settings/users/+page.svelte#L811-L826))
2. `<section><h2>ACE-Step Workers</h2>` — the empty placeholder ([lines 828-834](../frontend/src/routes/settings/users/+page.svelte#L828-L834)) ← **delete this**

**New ordering inside `tab === 'acestep'`:**
1. `<WorkerPoolPanel availableModes={registryModes} />` — top of the tab
2. `<ModelRegistryPanel onModesChange={(modes) => (registryModes = modes)} />` — directly below
3. `<section><h2>Available Models</h2>` — kept as-is, below the new panels
4. (No "Generation Defaults" section in this tab — that's `tab === 'generation'`. Verified.)

`registryModes` is a `$state<string[]>([])` declared in `+page.svelte`'s `<script>`. `ModelRegistryPanel` calls back via `onModesChange` whenever its poll returns a fresh response. `WorkerPoolPanel` consumes it for the Load dropdown. Shared via prop, not via a global store — keeps the data flow obvious.

**Why not three separate components?** "Available Models" is a fundamentally different feature (toggling which presets are exposed to non-admin users). It doesn't share state with the worker pool. Leaving it inline avoids a third extracted component just for ~20 lines.

## D9. Test strategy

The frontend test pattern is **Vitest + mocked `fetch` + mocked `EventSource`**. There's no MSW. There's no per-page test file today — `users/+page.svelte` has zero test coverage. **Decision:** match the existing convention (test the API client functions and the polling store; smoke-test the component behavior via store-level assertions, not DOM-level).

| Test file | Coverage |
|---|---|
| `frontend/src/lib/api/admin.test.ts` (**new**) | `listWorkers`, `getRegistry`, `loadModelOnWorker`, `evictModelOnWorker` — mock fetch, assert URL + method + body + parsed return value. Mirrors the existing [client.test.ts](../frontend/src/lib/api/client.test.ts) pattern. |
| `frontend/src/lib/stores/adminPolling.test.ts` (**new**) | `createPollingStore` — start/stop, interval firing, error handling, `document.hidden` pause. Use `vi.useFakeTimers()` to control the interval; mock `document.hidden` via a getter. Three or four tests. |
| `frontend/src/lib/stores/jobs.test.ts` (**update**) | Add: `trackJob` accepts `workerId`/`mode` in the context object and stores them. One short test, mostly to lock the contract so the new code isn't broken silently. |
| `frontend/src/lib/components/WorkerPoolPanel.test.ts` (**new, optional**) | Smoke-test renders an empty pool, renders one online worker with loaded models, renders an offline worker. Uses `@testing-library/svelte` if it's already a dep; if not, **skip this file** and rely on the polling store + API client tests for safety. Verify before writing. |
| `frontend/src/lib/components/ModelRegistryPanel.test.ts` (**new, optional**) | Same — render-smoke if testing-library/svelte exists, otherwise skip. |

**Verification step before writing component tests:** check `frontend/package.json` for `@testing-library/svelte`. If absent, do not add it as a new dependency (one new dep for one panel of tests is poor ROI). Existing tests use plain Vitest without testing-library; following that convention is correct.

**Coverage target:** 100% on the two new files (`adminPolling.ts`, the additions in `admin.ts`). The `.svelte` components are not measured by the existing coverage setup (frontend coverage in `pnpm test` covers `.ts`/`.js` only — verify in `vite.config.ts` / `vitest.config.ts`).

**Tests that would pass even if the impl is wrong (avoid):**
- ❌ Mocking `apiFetch` and asserting it was called (tests the test).
- ❌ Asserting the panel renders without checking what it renders.
- ❌ Mocking the polling store entirely and asserting the panel calls `start()` (vacuous).

## D10. Type generation — concrete edits to `scripts/generate_types.py`

Add to `_RESPONSE_MODEL_NAMES` (alphabetic position, Python dict insertion order is preserved since 3.7 but `_EMIT_ORDER` controls actual emission):
```python
"WorkerIdentity": "WorkerIdentityItem",
"WorkerEphemeralState": "WorkerEphemeralStateItem",
"WorkerInfo": "WorkerInfoItem",
"WorkerPoolResponse": "WorkerPoolResponse",
"RegistryModelResponse": "RegistryModelItem",
"RegistryResponse": "RegistryResponse",
```

Add to `_EMIT_ORDER` (after `JobItem` is fine — these don't depend on each other except `WorkerInfo` referencing `WorkerIdentity`/`WorkerEphemeralState`, so emit those first):
```python
"WorkerIdentityItem",
"WorkerEphemeralStateItem",
"WorkerInfoItem",
"WorkerPoolResponse",
"RegistryModelItem",
"RegistryResponse",
```

**Verify after running** `python scripts/generate_types.py`:
- `WorkerInfoItem` has fields `identity: WorkerIdentityItem`, `state: WorkerEphemeralStateItem | null`, `status: 'online' | 'loading' | 'offline'`.
- `WorkerEphemeralStateItem` has the optional fields correctly typed: `target_loading: string | null`, `vram_used_gb: number | null`, etc.
- `WorkerPoolResponse` has `workers: WorkerInfoItem[]`.
- The diff is minimal — no incidental changes to other types.

If the generator emits something unexpected (e.g. missing the `Literal` rendering), debug by adding a one-off `print(model.__name__, field.annotation)` call in `_model_to_interface` and re-running. **Don't refactor the generator** — it's been stable; just feed it the right inputs.

**Run `python scripts/generate_types.py --check`** before committing to confirm the file matches what the generator would produce (the existing CI guard).

## D11. Files Touched (Phase 4)

| File | Change |
|---|---|
| `scripts/generate_types.py` | Add 6 entries to `_RESPONSE_MODEL_NAMES`, 6 entries to `_EMIT_ORDER`. |
| `frontend/src/lib/api/types.ts` | **Regenerated** by `scripts/generate_types.py` — adds the 6 new interfaces. No manual edits. |
| `frontend/src/lib/api/admin.ts` | Append `listWorkers`, `getRegistry`, `loadModelOnWorker`, `evictModelOnWorker`. |
| `frontend/src/lib/api/client.ts` | Re-export the four new admin functions if the existing convention does so (verify; the page imports `fetchUsers` etc. from `$lib/api/client`, not `$lib/api/admin`). If yes, append the re-exports. |
| `frontend/src/lib/stores/jobs.ts` | Widen `trackJob`'s context type to include optional `workerId`, `mode`. No logic change. |
| `frontend/src/lib/stores/adminPolling.ts` | **New** — `createPollingStore<T>(fetcher, intervalMs)`. ~50 LOC. |
| `frontend/src/lib/components/WorkerPoolPanel.svelte` | **New** — full Worker Pool panel as in D2. |
| `frontend/src/lib/components/ModelRegistryPanel.svelte` | **New** — full Model Registry panel as in D3. |
| `frontend/src/routes/settings/users/+page.svelte` | Delete the "ACE-Step Workers" placeholder section. Mount `<WorkerPoolPanel>` and `<ModelRegistryPanel>` at the top of the `tab === 'acestep'` branch. Add `registryModes` state + the prop wiring. |
| `frontend/src/lib/api/admin.test.ts` | **New** — mocked-fetch tests for the 4 new functions. |
| `frontend/src/lib/stores/adminPolling.test.ts` | **New** — fake-timer tests for the polling store. |
| `frontend/src/lib/stores/jobs.test.ts` | Add: one test that `trackJob` stores `workerId` + `mode` on the context. |

**Files NOT touched in Phase 4:**
- Any backend Python file. Phase 4 is frontend-only.
- `acestep_worker/`, `acestep_engine/`, `scheduler.py`, `model_cache.py`, `jobs.py`, `admin_api.py` — backend boundary.
- `Dockerfile.worker`, `acestep-worker.Dockerfile` — Phase 8.
- `.env`, `.server.env` — local config.
- `plans/` other than this sub-plan.

## D12. Implementation order

Strict order. Each step leaves the tree compiling and the tests passing for the things that aren't yet rewritten.

1. **Read CLAUDE.md and this sub-plan one more time** (1 min)
2. **Update `scripts/generate_types.py`** — add entries to `_RESPONSE_MODEL_NAMES` and `_EMIT_ORDER`. (5 min)
3. **Run `python scripts/generate_types.py`**, inspect `frontend/src/lib/api/types.ts` for the new interfaces. If wrong, fix and re-run. (5 min)
4. **`frontend/src/lib/api/admin.ts`** — append the 4 new functions. (10 min)
5. **`frontend/src/lib/api/admin.test.ts`** — write the 4 tests. Run `pnpm test admin.test.ts`. (15 min)
6. **`frontend/src/lib/stores/jobs.ts`** — widen `trackJob` context type. (2 min)
7. **`frontend/src/lib/stores/jobs.test.ts`** — add the one new test. Run. (10 min)
8. **`frontend/src/lib/stores/adminPolling.ts`** — `createPollingStore`. (20 min)
9. **`frontend/src/lib/stores/adminPolling.test.ts`** — fake-timer tests. (30 min)
10. **`frontend/src/lib/components/ModelRegistryPanel.svelte`** — written first because it's smaller and feeds `availableModes` into the Worker Pool. (45 min)
11. **`frontend/src/lib/components/WorkerPoolPanel.svelte`** — the bigger one. (90 min)
12. **`frontend/src/routes/settings/users/+page.svelte`** — delete placeholder, mount the two panels, wire `registryModes`. (15 min)
13. **`pnpm check && pnpm lint`** in `frontend/`. Fix anything. (10 min)
14. **`pnpm test`** full frontend suite. Fix anything. (10 min)
15. **`python scripts/generate_types.py --check`** — confirm no diff. (1 min)
16. **Self-review pass** — `git diff` end-to-end, read every changed file. Look for dead imports, leftover console.logs, hardcoded strings. (20 min)
17. **Manual smoke test** — `timeout 120 docker compose up -d --build --wait` if local stack is up; otherwise hand-off to user for the smoke test. The user has a real GPU; this is the right place to involve them.
18. **Commit + push** in 1–2 commits per D14. (5 min)

Total wall clock: ~5 hours of focused work (frontend is faster than the cutover phases).

## D13. Self-review checklist (before commit)

1. **Re-read every changed file via `git diff HEAD~N`**. No skipping.
2. **`grep -rn "TODO\|FIXME\|XXX" frontend/src/lib/components/WorkerPoolPanel.svelte frontend/src/lib/components/ModelRegistryPanel.svelte frontend/src/lib/stores/adminPolling.ts`** — zero hits.
3. **No comments in new TS code** (per `feedback_code_standards.md`). Svelte component `<!-- ... -->` HTML comments are allowed only for non-obvious template logic and only if the structure can't be self-documenting.
4. **No hardcoded strings reused across files** — model mode names are pulled from the registry response, not hardcoded. Status colors/icons can live as `Final` constants at the top of the panel file (they're file-local, not cross-module config).
5. **`createPollingStore` cleans up `setInterval` AND the `visibilitychange` listener on `stop()`**. Easy to leak.
6. **Polling stops when the panel unmounts.** Verified by `onDestroy(() => store.stop())` in both panels. Test it: mount the panel, unmount, advance fake timers — no fetcher calls should fire.
7. **No SSE invented** — the load-model progress goes through the existing `trackJob` / `EventSource('/api/jobs/{id}/stream')` pipeline. No new EventSource created in Phase 4.
8. **Worker Pool spinner state correctly clears** — when a load job finishes (success or failure), the spinner overlay disappears within one poll tick (≤3 s). Verified by reading the activeJobs subscription.
9. **`pnpm check`** passes (Svelte type check). The new components have no implicit `any`s.
10. **`pnpm lint`** passes. No unused imports.
11. **`pnpm test`** passes — full frontend suite, not just the new tests.
12. **`python scripts/generate_types.py --check`** is a no-op (the generated file is in sync with the script).
13. **`docs/`** — no architecture/security/API docs need updating in Phase 4 (it's a UI swap, no new endpoints). **Verify** by checking whether `docs/architecture.md` mentions the admin UI shape; if it does, update the relevant sentence. Quick grep should be conclusive.

## D14. Things to watch out for

### Watchpoint 1: `EventSource` polyfills and credentials

The existing `jobs.ts` uses `new EventSource(url, { withCredentials: true })`. The browser native `EventSource` supports `withCredentials`; some polyfills don't. **No change needed in Phase 4** — we're reusing the existing pipeline. Just don't introduce a new `EventSource(...)` call without `{ withCredentials: true }`.

### Watchpoint 2: `document.hidden` in tests

`vi.useFakeTimers()` doesn't fake `document.hidden`. Mock it via `Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })`. Reset between tests. Alternative: bypass document entirely and pass a "isHidden" callback into `createPollingStore` for testability. **Decision:** pass a callback. Cleaner DI than mocking globals.

```typescript
export function createPollingStore<T>(
    fetcher: () => Promise<T>,
    intervalMs: number,
    options: { isHidden?: () => boolean } = {},
): PollingStore<T> { ... }
```

Default `isHidden` is `() => document.hidden`; tests pass their own.

### Watchpoint 3: Reactive state in Svelte 5 (runes)

The page uses `$state(...)` and `$derived(...)` — Svelte 5 runes mode. New components must also use runes. Don't accidentally write Svelte 4 `let` reactive variables. Check the existing `+page.svelte` script for the pattern (`let foo = $state(...)`).

### Watchpoint 4: Polling burst on first mount

When the panel mounts, `createPollingStore` should fire the fetcher **immediately** (not wait `intervalMs` for the first tick). Otherwise the panel shows an empty state for 3 s before any data appears. Implementation: call `fetcher()` once inside `start()`, then `setInterval(fetcher, intervalMs)`.

### Watchpoint 5: Race between Load action and the next poll

User clicks Load → `loadModelOnWorker` returns a job → spinner appears. Two seconds later, the 3 s poll fires and pulls fresh state. The fresh state still shows `target_loading === null` (because the worker hasn't started loading yet — it's waiting in the arq queue). The spinner from `activeJobs` is what guarantees the UI looks "loading". **Don't gate the spinner on `state.target_loading`** — gate it on the activeJobs presence. Otherwise there's a 1–2 s window where the user sees no feedback after clicking.

### Watchpoint 6: Multiple workers, one in `activeJobs` for a different worker

The `activeJobs` global store contains all in-flight jobs (generation jobs from other tabs, load jobs from this tab, etc.). The Worker Pool panel must filter by `job.workerId === card.identity.id` AND the job type being a load job. Don't accidentally show a spinner on worker-0 because worker-1 has a load in flight, and don't show a spinner on either worker just because the user has a generation in progress in another tab.

**The filter:** `activeJobs.find(j => j.workerId === card.identity.id && j.job.type === 'load_model_on_worker')`. The job type is set server-side by `create_job(db, "load_model_on_worker", ...)` ([admin_api.py:391](../src/songmaker_cli/admin_api.py#L391)) — verify the exact string.

### Watchpoint 7: `apiFetch` 403 handling

The existing `apiFetch` ([frontend/src/lib/api/fetch.ts](../frontend/src/lib/api/fetch.ts)) auto-redirects on 401 (calls `clearAuth` + `goto('/login')`). Verify what it does on 403. If it doesn't auto-redirect (likely — 403 means "logged in but no admin"), the panel must catch the 403 and show a local "Admin access required" state. **Read `fetch.ts` end-to-end before writing the error handlers.** It's small.

### Watchpoint 8: `scripts/generate_types.py --check` in CI

If CI runs `--check` and the regenerated file would differ, CI fails. Make sure the regenerated `types.ts` is committed in the same commit as the `generate_types.py` change. **Don't split** the generator update from the regenerated output across commits.

### Watchpoint 9: VRAM units mismatch

`WorkerEphemeralState.vram_used_gb` and `vram_total_gb` are floats in GB. The worker writes them via NVML. `identity.vram_total_gb` is **also** a float in GB but written at registration time (unchanging). The two `vram_total_gb` fields should agree but might not (e.g. different driver versions report differently). **Decision:** display `state.vram_used_gb / state.vram_total_gb` if both are present; fall back to `identity.vram_total_gb` for the static "GPU 0 • 24 GB" header line. Don't try to reconcile them.

### Watchpoint 10: Polling store error throttling

If `listWorkers()` starts failing, the polling store will call it every 3 s forever. **Mitigation:** after N consecutive failures (say 5), stop polling and surface the error. The user can manually refresh. Implementation in `createPollingStore`:

```typescript
let consecutiveErrors = 0;
const MAX_ERRORS = 5;
async function tick() {
    try {
        data = await fetcher();
        consecutiveErrors = 0;
    } catch (e) {
        consecutiveErrors++;
        error = e;
        if (consecutiveErrors >= MAX_ERRORS) stop();
    }
}
```

The panel's "Refresh" button calls `start()` again to reset.

### Watchpoint 11: Don't pass `JobItem` from `loadModelOnWorker` to `trackJob` directly

`trackJob` expects a `JobStatus` (which is `JobItem`). They're the same type via the alias in `fetch.ts:66`. ✓ no conversion needed. Just import `JobItem` from `types` in `admin.ts` so the return type is explicit.

### Watchpoint 12: The Restart and Pin buttons are tempting

The parent plan's draft ASCII shows `[Restart]` and the registry section mentions a "Pin" stub. Both endpoints are unshipped (Phase 6). **Do not add disabled placeholder buttons.** The reasoning:
- Disabled buttons that never become enabled are visual debt.
- Phase 6 will have its own UI pass.
- "Coming when multi-GPU lands" tooltips age badly.

If the user (during review) wants to see the buttons even as stubs, add them then. Default position: omit.

## D15. What is NOT in Phase 4 (deferred)

- **Restart button / endpoint** → Phase 6
- **Pin button / `pin_model` LRU exemption** → Phase 6
- **Download button (functional)** → Phase 5
- **Per-loaded-model VRAM display** → would need a backend response field; defer
- **Loading elapsed-time counter** → would need a `loading_started_at` field in heartbeat; defer
- **Worker metrics graphs** → Phase 6 (Prometheus integration)
- **Component DOM tests via @testing-library/svelte** → only if it's already a dep; otherwise defer
- **Extracting "Available Models" toggle into its own panel** → out of scope; that's a separate feature

If you find yourself implementing any of these in Phase 4, **stop**.

## D16. Branching + commits

Phase 4 commits go on `feat/acestep-worker-pool`. Suggested split:

1. **Type generation + API client + jobs.ts widening** — `scripts/generate_types.py`, regenerated `types.ts`, `admin.ts` additions, `jobs.ts` type widening, `admin.test.ts` + `jobs.test.ts` updates. This commit alone leaves the tree green and ready for the panels.
2. **Polling store + panels + page wiring** — `adminPolling.ts` + tests, both `.svelte` panels, `+page.svelte` integration. The bigger commit.

Or one commit if the splits feel forced. Per `feedback_speed.md` (fewer intermediate test runs), **two commits is the recommended ceiling** — don't fragment further.

Push to `origin/feat/acestep-worker-pool` after the second commit.

## D17. Verification (manual smoke test, runs after implementation)

The user has a real GPU + the full stack. Smoke test by hand:

1. `timeout 120 docker compose up -d --build --wait`
2. Open `http://localhost:8080/settings/users` as an admin user.
3. Click the **ACE-Step** tab.
4. **Worker Pool panel** should show one card (`acestep-worker-0`), status `Idle` or `No model loaded` depending on whether a model is currently loaded.
5. Click **Load model ▾** → select `sft` (or whichever isn't currently loaded) → click Load.
6. Card should immediately show a spinner with "Loading sft…" — within ~5 s of clicking.
7. After 30–90 s, spinner clears, "Loaded: sft" appears, status becomes `Idle`.
8. Click **Evict sft** → button disables briefly → state returns to `No model loaded`.
9. **Model Registry panel** should show 5 rows (sft, turbo, xl-sft, xl-turbo, xl-base). All `✓ downloaded` if `scripts/download_models.sh` was run; `xl-base` may be `✗ not downloaded`. The Download button is disabled with a tooltip about Phase 5.
10. Open DevTools → Network tab. Filter for `/api/admin/`. Confirm `/workers` polls every 3 s, `/registry` every 5 s.
11. Switch to a different browser tab (so `document.hidden === true`). Wait 30 s. Switch back. Confirm in Network that no polls fired while hidden, and a fresh poll fires immediately on visibility regain.
12. Open a non-admin user session in another browser. Navigate to `/settings/users`. Page-level "Admin access required." should appear (no panel-level error needed because the page guards before the panels mount). ← Verify the existing `{#if !admin}` block still triggers — Phase 4 doesn't change page-level auth.
13. Stop `acestep-worker-0` (`docker compose stop acestep-worker-0`). Within 15 s (Redis TTL), the Worker Pool card should show status `Offline (no heartbeat)`. Restart the worker. Within 5 s, status returns to `Idle`.
14. Open the browser console. Confirm zero JavaScript errors during the entire walkthrough.

If any step fails, **fix before committing the panels**. The polling store + API client tests are not enough on their own — the integration is what the smoke test catches.

## D18. Quick context for next session's first message

If you're a new agent picking this up: read `CLAUDE.md`, then [acestep-worker-pool.md](acestep-worker-pool.md), then this file. Phase 1 = `c416194`, Phase 2 = `275518c`, Phase 3 = `74b8576`. Branch is `feat/acestep-worker-pool`.

The biggest single risk in Phase 4 is the **type generation gap** (D10) — `frontend/src/lib/api/types.ts` is missing the worker types entirely, and the existing `scripts/generate_types.py` uses curated allowlists that nobody updated in Phase 2/3. Fix that first; everything else mechanically follows.

The second-biggest risk is **inventing a parallel SSE pipeline** for load-model progress instead of reusing `trackJob` + `/api/jobs/{id}/stream`. Don't do that. The backend already creates a real `Job` row (D5) — the existing pipeline handles it for free.
