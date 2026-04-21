# Songmaker Backlog

All future work as concept notes. Per [CLAUDE.md "Plan-writing convention"](CLAUDE.md#plan-writing-convention), each entry captures **goal + locked-in decisions + hard constraints**. The executing agent reads the live code, designs the implementation in-session, and executes. Do not re-prompt the user for already-locked decisions.

**Before executing, always analyze.** Backlog entries rot. The premise may be wrong, the work may be partly done, the threshold may collide with an existing one, the file the entry references may have been renamed. **First step on every item: read the live code and verify the entry's premise still holds.** If it doesn't — stop, surface the discrepancy to the user, and discuss what's actually worth doing. Don't execute a stale spec just because it's written down. The 30 seconds of "wait, this doesn't match what I'm seeing" is worth more than an hour of building the wrong thing.

When you finish an item, delete its section. Git history preserves it. Decisions and reasoning are also captured in the commit messages.

---

## Feature work (priority order — top = most valuable)

### 1. LoRA voice training

**Goal:** Let Felix train custom voice/style LoRAs from his own vocal recordings and use them in generation. Upload vocal samples → background training job → trained LoRA appears in the model picker → generation can apply it.

**Decisions** (locked in from upstream research 2026-04-21):
- Use ACE-Step's native trainer — `vendor/acestep` ships `trainer.py` + a documented LoRA training tutorial + a Gradio "LoRA Training" tab. We do NOT build our own trainer.
- Use **LoKR** adapters (not plain LoRA). Upstream reports ~10× faster training than LoRA (~1 hour → ~5 minutes) on consumer hardware with no quality loss.
- Training data floor: "a handful of tracks" per upstream docs. Minimum we document to users: 3–5 clean vocal takes, 30–90 seconds each.
- Three-stage pipeline mirrors upstream: `DatasetBuilder` (scan + metadata + optional auto-label) → preprocess → train via `trainer.py --lora_config_path …`.
- Storage: trained LoRAs go in a new `user_loras/{user_id}/` directory under the existing audio volume. DB row in a new `UserLora` table (user_id, name, path, created_at, status). Appear in the generation model picker as "Your voice: {name}".
- Training is a background ARQ job (new `lora_training` job type), runs on the acestep-worker's GPU. Blocks generation on that worker while running — acceptable for a single-user deployment.
- Ownership: `created_by` FK, normal ownership checks.

**Constraints:**
- Must not break existing generation pipeline. Training + generation share one GPU — serialize via the existing job queue.
- Upload size cap (e.g. 100 MB per batch) to prevent runaway disk usage.
- Training failures must clean up partial LoRA files + mark the DB row `FAILED` — don't orphan half-trained artifacts.
- Audit-log training start + completion.

**References:**
- [upstream LoRA tutorial](https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/LoRA_Training_Tutorial.md)
- [DeepWiki LoRA training system](https://deepwiki.com/ace-step/ACE-Step-1.5/6-lora-training-system)
- [community LoRA builder scripts](https://github.com/leewinder/ace-step-lora-builder)
- [example community LoRAs](https://huggingface.co/m125148/ACE-Step-v1.5-raspy-vocal-and-instrumental-5-LoRAs)

**First step:** read `vendor/acestep/docs/en/LoRA_Training_Tutorial.md`, `vendor/acestep/trainer.py`, our `src/acestep_worker/`, and `src/songmaker_cli/db/models.py`. Design the `UserLora` model + new `lora_training` job + upload endpoint + model-picker wiring. Execute.

---

### 2. Co-writer reliability (timeout / latency investigation)

**Goal:** Co-writer hit the 600s chat-timeout wall once already — bumped to 600s in commit `1dc4038` as a plaster. Investigate the actual latency contributors and fix the root cause, without swapping the provider.

**Decisions:**
- Stay on Claude CLI subprocess + Max subscription. SDK migration is rejected on cost grounds (see `feedback_claude_cli_vs_sdk.md`).
- Fix locally: don't introduce SSE streaming as a rewrite — if CLI-side streaming (`--output-format stream-json`) can be read incrementally without rewriting `claude/provider.py`, ship that; otherwise fix the dominant latency.

**Open questions** (investigation first — these aren't decisions yet):
- Where is the time going on a slow turn? CLI subprocess cold start? MCP server tool-loop latency? Tool result size? Claude model thinking tokens?
- Is the 600s sometimes still not enough for multi-tool-call turns?

**Constraints:**
- No provider swap. No SDK. No `ANTHROPIC_API_KEY` requirement.
- Don't regress the current successful paths while fixing the slow ones.

**First step:** instrument a slow co-writer turn end-to-end (client send → server receive → CLI spawn → tool calls → final token → client render). Find the dominant contributor. Decide the fix. Implement.

---

### 3. Move resources (generation→song, song→album)

> ⚠️ **Premises below must be verified before execution** — background agent spawned 2026-04-21 to check. Do NOT start implementation until verification lands.

**Goal:** Let the user move a generation to a different (song, version), and move a song to a different album. Primary claimed use case: post-recovery cleanup where anonymous WAVs land in a "Recovered" album and need reassignment to their real songs and albums.

**Premises to verify first:**
- Does the "Recovered" album / post-recovery WAV-ingestion flow actually exist? If no, the primary use case evaporates and the feature's value shrinks to "nice to have."
- Does `AuditAction.MOVE` exist in the enum?
- Do `Playlist` rows reference `song_id` (so moving a song between albums doesn't break them)?
- Is there a `track_number` on `Song` and is it `UNIQUE(album_id, track_number)` or similar?

**Decisions** (conditional on premises holding):
- One shared `MoveResourceDialog.svelte` for both moves. Tree picker (album → song → version) scoped to resources the user owns.
- Two endpoints, bundled in one PR because they share the dialog and safety patterns:
  - `POST /api/generations/{id}/move` with `target_song_id` + optional `target_version_id` (default: latest version on destination song).
  - `POST /api/songs/{id}/move` with `target_album_id`.
- Both audit-logged with the existing `MOVE` action (if it exists — see premises).
- "Move to..." entry in the existing context menu.
- Double ownership check: user must own both source and destination.
- The audio file path does NOT move on disk — only DB rows change. Paths stay stable.

**Destination-side bookkeeping:**
- **Move generation**: transfer `is_picked` only if source was picked AND destination song has no current pick. Always preserve `is_kept`. Assign next available `generation_number` on the destination version.
- **Move song**: assign next `track_number` on destination album. Playlist references survive as-is (if premise holds). If source song was the album cover, the old album loses its cover.

**Constraints:**
- Ownership check on both source and destination.
- Single transaction per move. No partial state on failure.

**First step:** wait for the verification agent's report. Then, if premises hold, read `Generation` + `Song` models + `db/queries/generations.py` + `db/queries/songs.py` + the context menu component, design + execute.

---

### 4. Use `ACESTEP_CHECKPOINTS_DIR` env var

**Goal:** Upstream #1056 added `ACESTEP_CHECKPOINTS_DIR` for shared model-weights storage. Consume it instead of hardcoding the checkpoint mount path in `docker-compose.yml` and worker settings. Small config cleanup, not a feature.

**Decisions:**
- Set `ACESTEP_CHECKPOINTS_DIR=/models` (or whatever the current mount is) in `docker-compose.yml` for acestep-worker.
- Remove any hardcoded checkpoint path constant in `src/acestep_worker/settings.py` / `src/acestep_engine/settings.py` that duplicates this.
- No DB/API changes, no user-facing change.

**Constraints:**
- Don't break existing volume mounts — the env var must point at the same directory that's already populated.
- Verify upstream PR #1056 actually shipped and the env var is honored in the `vendor/acestep` submodule we currently pin. If not, this item is a no-op.

**First step:** grep the repo for checkpoint path hardcoding (`grep -rn "/models\|checkpoints" docker-compose.yml src/acestep_worker src/acestep_engine`), read the ACE-Step code that consumes `ACESTEP_CHECKPOINTS_DIR`, wire it up.

---

### 5. Claude SDK migration + streaming — DORMANT

**Goal:** Two coupled changes: (a) drop the Claude CLI subprocess backend in favor of the official `anthropic` SDK only, (b) add SSE streaming responses to the co-writer. Both rewrite `claude/provider.py` + `chat_api.py` + `ClaudeChat.svelte` — bundle them so the surface is touched once.

**Status:** Dormant. Do not start until one of the triggers below fires.

**Decisions** (locked in for when it eventually runs):
- SDK-only — delete the CLI subprocess backend, `_DISALLOWED_TOOLS` denylist, and the docker-compose bind mounts (`~/.local/bin/claude`, `~/.claude`, `~/.claude.json`).
- Streaming via SSE, frontend reads the stream incrementally.
- Circuit breaker around Anthropic calls (open after 3 consecutive failures).

**Triggers to start:**
- Explicit user decision to leave the Max subscription for `ANTHROPIC_API_KEY`. (2026-04-21: NO — Max sub is already expensive, per-token on top roughly doubles the AI bill.)
- Public-facing launch (CLI denylist is fail-open, unsuitable for untrusted users).

**Non-triggers** (do NOT start just because these happen):
- Co-writer chat timeouts in the wild — fix with item #2 instead.
- Co-writer becomes a daily-driver feature — CLI wrapper is fine.

---

### 6. Tune xl-turbo / xl-sft APG defaults — USER-ONLY, NOT AGENT WORK

**Goal:** Audit the per-mode defaults for the 5 APG params we exposed via upstream PR #1092 (`sampler_mode`, `velocity_norm_threshold`, `velocity_ema_factor`, `latent_shift`, `latent_rescale`) against community-recommended XL values. Bad defaults are the prime suspect for xl-turbo/xl-sft quality issues — defaults were picked without reference to anything.

**Why this isn't in the agent queue:** the hard constraint is "A/B listen and pick." Audible audio quality is Felix's ears, not a headless agent's. Keep the entry as a shared reference note for when Felix + Claude sit down together.

**Reference values** (from websearch 2026-04-21):
- xl-sft community recipe: `euler` sampler, normal scheduler, 46 steps, CFG 7.3, APG `eta=1.05`, `norm_thresh=1.3`, `momentum=0.0`.
- xl-turbo: less documented. Turbo distillation means CFG is off, so APG params matter less — but still should match the xl-sft values where they apply.
- Exact `eta / norm_thresh / momentum` → our-5-param mapping needs verification against `vendor/acestep/acestep/api/http/release_task_param_parser.py` — the names don't line up 1:1.

**Process when we do it:**
1. Read the param parser + current defaults in `acestep_capabilities.py`.
2. Verify the name mapping.
3. Generate A/B pairs with current vs proposed defaults on the same seed.
4. Felix picks. Commit the winner.
