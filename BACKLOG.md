# Songmaker Backlog

All future work as concept notes. Per [CLAUDE.md "Plan-writing convention"](CLAUDE.md#plan-writing-convention), each entry captures **goal + locked-in decisions + hard constraints**. The executing agent reads the live code, designs the implementation in-session, and executes. Do not re-prompt the user for already-locked decisions.

**Before executing, always analyze.** Backlog entries rot. The premise may be wrong, the work may be partly done, the threshold may collide with an existing one, the file the entry references may have been renamed. **First step on every item: read the live code and verify the entry's premise still holds.** If it doesn't — stop, surface the discrepancy to the user, and discuss what's actually worth doing. Don't execute a stale spec just because it's written down. The 30 seconds of "wait, this doesn't match what I'm seeing" is worth more than an hour of building the wrong thing.

When you finish an item, delete its section. Git history preserves it. Decisions and reasoning are also captured in the commit messages.

## Dates visible + sort/filter by recency (Felix, 2026-07-07)

**Goal:** Felix can see WHEN albums/songs/generations were created and find
"the latest" without hunting. Verbatim: "i dont see dates so its hard to see
what is a latest album song or whatever — i also cannot sort or filter by
that."

**Locked-in decisions:** relative dates on cards/rows ("2h ago" style, exact
timestamp on hover/detail — matches the atelier convention: relative in
lists, absolute in detail); a sort control (newest-first default is
acceptable) on the album and song lists; created_at already exists on the
models — this is read-side + UI only.

**Hard constraints:** no schema change; keep list payloads light (created_at
is already serialized or trivially added); the sort/filter belongs where the
existing list controls live — no new panel.


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

### 3. Use `ACESTEP_CHECKPOINTS_DIR` env var

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

### 4. Claude SDK migration + streaming — DORMANT

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

### 5. Tune xl-turbo / xl-sft APG defaults — USER-ONLY, NOT AGENT WORK

**Goal:** Audit the per-mode defaults for the 5 APG params we exposed via upstream PR #1092 (`sampler_mode`, `velocity_norm_threshold`, `velocity_ema_factor`, `latent_shift`, `latent_rescale`) against community-recommended XL values. Bad defaults are the prime suspect for xl-turbo/xl-sft quality issues — defaults were picked without reference to anything.

**Why this isn't in the agent queue:** the hard constraint is "A/B listen and pick." Audible audio quality is Felix's ears, not a headless agent's. Keep the entry as a shared reference note for when Felix + Claude sit down together.

**Verified mapping** (2026-04-21 research agent):

| Community term | Our param | Currently exposed? |
|---|---|---|
| `norm_thresh` | `velocity_norm_threshold` | ✅ yes |
| `eta` | — | ❌ not wired to HTTP surface |
| `momentum` | — | ❌ not wired (MLX hardcoded; PyTorch internal only) |
| sampler | `sampler_mode` (`"euler"` \| `"heun"`) | ✅ yes |
| — | `latent_shift` / `latent_rescale` | ✅ yes, but post-diffusion scale, not APG |

Only `velocity_norm_threshold` + `sampler_mode` match the community APG recipe. `eta` and `momentum` would need a follow-up upstream PR on top of #1092.

**Current defaults** (all modes share `_SHARED_DEFAULTS` in `src/songmaker_cli/config.py:103-107`):
- `velocity_norm_threshold = 0.0` (off)
- `velocity_ema_factor = 0.0` (off)
- `latent_shift = 0.0`, `latent_rescale = 1.0`
- `sampler_mode = "euler"`

**Recommended A/B candidates:**

| Mode | `sampler_mode` | `velocity_norm_threshold` | Rationale |
|---|---|---|---|
| `xl-turbo` (Felix's prod) | `"heun"` | `1.5` | 8-step distilled benefits from second-order predictor; clamping is the only stabilization with CFG off |
| `xl-sft` | `"euler"` | `1.3` | Direct match to community xl-sft recipe |

**Process:**
1. Generate A/B pairs on the same seed: current defaults vs proposed.
2. Felix listens. Commits whichever.
3. Optional follow-up PR on top of #1092: expose `eta` + `momentum` so the full recipe is reachable.
