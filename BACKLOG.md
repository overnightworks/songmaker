# Songmaker Backlog

All future work as concept notes. Per [CLAUDE.md "Plan-writing convention"](CLAUDE.md#plan-writing-convention), each entry captures **goal + locked-in decisions + hard constraints**. The executing agent reads the live code, designs the implementation in-session, and executes. Do not re-prompt the user for already-locked decisions.

When you finish an item, delete its section. Git history preserves it. Decisions and reasoning are also captured in the commit messages.

---

## Architecture cleanup (deferred from the 2026-04-09 review)

These two items remain from the brutal architecture review. The other 10 findings (B1–B7, B10–B12) shipped — see commit messages from 2026-04-09 for the audit trail. Sequence them after the no-silent-fallbacks branch merges to main.

### Stuck-`QUEUED` job recovery (B8)

**Goal:** Jobs that sit in `QUEUED` because no worker is online never get marked stale. The recovery cron only checks heartbeat staleness on `RUNNING` jobs. User sees "queued" forever.

**Decisions:**
- `QUEUE_MAX_AGE_SECONDS = 600` (10 min). Add as a `Settings` field.
- Failure message: `"No worker available for {job_type} after {QUEUE_MAX_AGE_SECONDS}s — please retry."`
- Extend the existing `recover_stale_jobs_by_age` cron rather than adding a new task.

**Constraints:**
- The cleanup cron already runs every 2 min — no scheduling change needed.
- Use the existing `_list_online_workers()` from the scheduler to detect "no worker available."

**First step:** read `db/queries/jobs.py:recover_stale_jobs_by_age` + the scheduler's worker discovery, design + execute.

### Backpressure UI (B9)

**Goal:** Queue depth is exposed in `/health` and `/metrics` but the frontend doesn't show it. Users submit blindly and may queue dozens of jobs without realizing the wait. Surface queue pressure in the UI as a 3-layer design.

**Decisions:** three layers, all locked in:
- **Layer 1:** always-visible queue depth hint under the submit button. New `lib/stores/queue.ts` polling `/health`.
- **Layer 2:** position-in-queue while waiting. New `queue_position: int | None` field on the job-status response (count of older queued jobs of same `job_type`).
- **Layer 3:** disable submit button when global queue depth ≥ `max_queue_depth`. New `queue_depth_cap_reached: bool` on `/health`.

**Constraints:**
- Coordinate with B8 if shipped in the same PR — both add fields to the `JobResponse` Pydantic model.
- May need a new index on `(job_type, status, created_at)` for the `queue_position` query if not already present.

**First step:** read `health_api.py`, the existing `JobResponse` Pydantic model, and the frontend `GenerateButton.svelte` + jobs store, design + execute.

---

## Feature work (product-driven, no sequencing)

After the architecture cleanup, these are the bigger features in the queue. They're all independent — pick by product value, not by file order.

### Claude SDK migration + streaming

**Goal:** Two coupled changes: (a) drop the Claude CLI subprocess backend in favor of the official `anthropic` SDK only, (b) add streaming responses to the co-writer. Both rewrite `claude/provider.py` + `chat_api.py` + `ClaudeChat.svelte` — bundle them so the surface is touched once.

**Decisions:**
- SDK-only — delete the CLI subprocess backend, the `_DISALLOWED_TOOLS` denylist, and the docker-compose bind mounts (`~/.local/bin/claude`, `~/.claude`, `~/.claude.json`).
- Streaming via SSE on the chat endpoint, frontend reads the stream incrementally.
- Add a circuit breaker around Anthropic calls (open after 3 consecutive failures, short-circuit subsequent requests).

**Triggers to start:**
- Co-writer becomes a daily-driver feature.
- Frontend reports a chat timeout in the wild (the 120s wall is hit).
- Switch from Max subscription / CLI to a paid `ANTHROPIC_API_KEY`.
- Public-facing launch (CLI denylist is fail-open and unsuitable for untrusted users).

**Constraints:**
- `ANTHROPIC_API_KEY` becomes required (not optional). Settings raises at startup if missing.
- Frontend must handle partial-response state (cursor, cancel button).

**First step:** read `claude/provider.py`, `chat_api.py`, `ClaudeChat.svelte`, design + execute as a single coordinated PR.

### Frontend component split (Phase 2)

**Goal:** Two god components in the frontend — `GenerationView.svelte` (~845 lines) and `SongDetailView.svelte` (~802 lines) — mix unrelated concerns (score display, action bar, playlist picker, delete confirmation, job tracking, tab routing, editor, version timeline, sharing, repaint/cover dialogs). Split them into focused components and add component test scaffolding (currently zero component tests, only stores + utils are tested).

**Decisions:**
- Functional split only — no visual redesign, no new features.
- Add component test scaffolding using `@testing-library/svelte` + `vitest`.
- Highest-leverage frontend work — every other frontend D-item depends on this.

**Constraints:**
- Backend stays unchanged. Pure frontend refactor + new tests.
- Stores stay unchanged (separate concern).

**First step:** read both components + the existing store layer, design the split (probably 5-10 new focused components per god component), execute.

### ACE-Step Base model tasks (Lego, Extract, Complete)

**Goal:** Expose ACE-Step's Base-DiT-only audio manipulation modes that aren't currently deployed: Lego (layer instruments on existing audio), Extract (stem separation), Complete (add accompaniment to a solo track). Requires the `acestep-v15-base` model variant.

**Decisions:**
- Each mode is its own `task_type` value in the discriminated union (`lego`, `extract`, `complete`).
- Validate that the Base model is loaded before accepting any of these jobs — reject otherwise.
- Frontend gets a dedicated "Audio Tools" panel separate from generation settings.

**Constraints:**
- Requires the W2 discriminated-union shape from `no-silent-fallbacks-v2`. The new task types extend `RepaintParams` / `CoverParams`-style classes.
- The `acestep-v15-base` model is not currently in production. Decide whether to download + pin it, or leave it as opt-in.

**First step:** read the post-W2 `api_models/generation_params.py` discriminated union and the ACE-Step submodule's task-type handling, design + execute.

### LoRA voice training

**Goal:** Let users train custom voice models (LoRA) from their own vocal recordings and use them in generation. The user uploads vocal samples → background training job → trained LoRA appears in the model picker.

**Open questions** (must answer before starting — these are NOT locked-in decisions):
- Does ACE-Step 1.5 support LoRA inference natively, or is a custom adapter needed?
- What training framework? ACE-Step's own, RVC, or Applio?
- What's the minimum audio quality/length for usable results?

**Constraints:**
- Training is GPU-bound and slow — must be a background job, not a synchronous API call.
- Stored LoRAs are user-owned (`created_by` ownership check).

**First step:** answer the open questions via prototyping. Don't start the full feature until you know the answer to "does ACE-Step support LoRA at all."

### E2E testing infrastructure (Playwright)

**Goal:** Set up Playwright + write E2E tests covering auth, ownership, CRUD, player, and mobile viewports. Currently zero E2E tests — only Python integration tests + frontend unit tests exist.

**Decisions:**
- Playwright (not Cypress).
- Phase 1: Playwright setup + auth tests (catch security regressions).
- Phase 2: ownership + CRUD tests (catch permission bugs).
- Phase 3: player + mobile viewport tests (catch UI regressions).
- Phase 4: CI integration.

**Constraints:**
- Tests run against a real Docker stack (not mocked), so they need a `docker compose up` lifecycle in CI.
- Slow-by-design — don't gate every PR on the full E2E suite, run on `main` merges only.

**First step:** read existing test infrastructure, install Playwright, write the auth phase first. Don't try to do all 4 phases in one PR.

### Move generation between songs

**Goal:** Lets the user move a `Generation` row from one (song, version) to another via the UI. Designed primarily for the post-recovery cleanup workflow where N anonymous WAVs land in a "Recovered" album and need reassignment to their real songs.

**Decisions:**
- New endpoint `POST /api/generations/{id}/move` taking `target_song_id` + `target_version_id` (optional, defaults to latest).
- Audit-logged with `MOVE` action (already in `AuditAction` enum).
- Frontend exposes it via a "Move to..." action in the generation context menu.
- Updates `is_picked` / `is_kept` flags on the destination correctly (transfer them iff the source was picked/kept and the destination has none).

**Constraints:**
- Ownership check — can only move generations owned by the current user (or admin).
- The audio file path doesn't move on disk — only the DB row changes. The path remains stable.
- Don't break version_number / generation_number sequences on the destination.

**First step:** read `Generation` model + `db/queries/generations.py` + the existing context menu component, design + execute.
