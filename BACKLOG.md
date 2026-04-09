# Songmaker Backlog

All future work as concept notes. Per [CLAUDE.md "Plan-writing convention"](CLAUDE.md#plan-writing-convention), each entry captures **goal + locked-in decisions + hard constraints**. The executing agent reads the live code, designs the implementation in-session, and executes. Do not re-prompt the user for already-locked decisions.

**Before executing, always analyze.** Backlog entries rot. The premise may be wrong, the work may be partly done, the threshold may collide with an existing one, the file the entry references may have been renamed. **First step on every item: read the live code and verify the entry's premise still holds.** If it doesn't — stop, surface the discrepancy to the user, and discuss what's actually worth doing. Don't execute a stale spec just because it's written down. The 30 seconds of "wait, this doesn't match what I'm seeing" is worth more than an hour of building the wrong thing.

When you finish an item, delete its section. Git history preserves it. Decisions and reasoning are also captured in the commit messages.

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

**Goal:** `GenerationView.svelte` and `SongDetailView.svelte` are god components that mix unrelated concerns (score display, action bar, playlist picker, delete confirmation, job tracking, tab routing, editor, version timeline, sharing, repaint/cover dialogs). Split them into focused components and add component test scaffolding (currently zero component tests, only stores + utils are tested).

**Decisions:**
- Functional split only — no visual redesign, no new features.
- Add component test scaffolding using `@testing-library/svelte` + `vitest`.

**Triggers to start:**
- Next non-trivial feature lands in either god component and the diff is hard to reason about.
- A bug in one of the embedded concerns is hard to isolate because of the size.
- Until then, pure-refactor risk (breaking 1700+ lines of working UI) outweighs the benefit.

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

### Rename songs and albums (inline edit)

**Goal:** Let the user rename a song or album from the UI. Currently the title is set at creation and never changes — typos and "untitled" placeholders linger forever.

**Decisions:**
- One shared `EditableTitle.svelte` component used by both the song detail view and album header. Click-to-edit, blur-to-save, Esc-to-cancel.
- Two endpoints: `PATCH /api/songs/{id}` and `PATCH /api/albums/{id}`, both accepting `{title: string}`. Same Pydantic shape, different ownership check.
- Audit-logged with the existing `UPDATE` action.
- Slug regeneration: rerun `slugify()` on the new title and update `share_slug` only if the share is currently disabled. If sharing is on, keep the old slug to avoid breaking shared links.

**Constraints:**
- Ownership check on both endpoints.
- Validation: non-empty after trim, ≤ existing column width.
- Bundle both endpoints + the shared component in one PR — splitting them duplicates `EditableTitle.svelte` for no gain.

**First step:** read `Song` and `Album` models + `db/queries/songs.py` and `db/queries/albums.py` + the song/album header components, design + execute.

### Move resources (generation→song, song→album)

**Goal:** Let the user move a generation to a different (song, version), and move a song to a different album. Primary use case: post-recovery cleanup where anonymous WAVs land in a "Recovered" album and need reassignment to their real songs and albums.

**Decisions:**
- One shared `MoveResourceDialog.svelte` for both move operations. It takes the resource type, source ID, and a tree picker (album → song → version) scoped to resources the user owns.
- Two endpoints, bundled in one PR because they share the dialog and the safety patterns:
  - `POST /api/generations/{id}/move` with `target_song_id` + optional `target_version_id` (defaults to latest version on the destination song).
  - `POST /api/songs/{id}/move` with `target_album_id`.
- Both audit-logged with the existing `MOVE` action.
- Both expose the action via a "Move to..." entry in the existing context menu.
- Double ownership check: user must own both source and destination.
- The audio file path doesn't move on disk for either operation — only DB rows change. Paths stay stable.

**Destination-side bookkeeping (the actual edge cases):**
- **Move generation**: transfer `is_picked` only if the source was picked AND the destination song has no current pick. Always preserve `is_kept`. Don't break the destination version's `generation_number` sequence — assign the next available number on the destination version.
- **Move song**: assign the next available `track_number` on the destination album. Playlist references survive as-is (they reference `song_id`, not `album_id`). If the source song was the album cover for its old album, the old album loses its cover.

**Constraints:**
- Ownership check on both source and destination.
- Single transaction per move — partial state on failure is unacceptable.
- The existing `MOVE` action in `AuditAction` covers both — no enum change needed.

**First step:** read `Generation` and `Song` models + `db/queries/generations.py` + `db/queries/songs.py` + the existing context menu component, design + execute.
