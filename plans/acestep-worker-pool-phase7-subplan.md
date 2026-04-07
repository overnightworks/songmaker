# Phase 7 Sub-plan — Post-implementation cleanup sweep

> **Phase 7 is the cleanup phase.** It runs after all 6 implementation phases of [acestep-worker-pool.md](acestep-worker-pool.md) have shipped. Not after Phase 3; not after Phase 4. **After Phase 6.** The full worker pool architecture — scheduler, control plane, admin UI, downloads, observability — must be in place and stable before Phase 7 runs.
>
> **Why a dedicated phase and not a sub-step of Phase 6:** each phase's own self-review (e.g. Phase 3's D15) catches the dead code that phase creates. But cross-cutting cleanup — `CLAUDE.md` debt entries, `docs/` consistency between Phase 3 and Phase 6 writes, frontend grep after Phase 4 rewrites the admin tab, stale env files — benefits from a single pass at the end when everything is in its final state. Rolling it into Phase 6 would conflate polish-feature work with cleanup; keeping it as Phase 7 makes the cleanup commit reviewable on its own.
>
> **Size:** 1–2 hours. **One commit.** No new features, no refactors, just deletions and doc updates.

## Pre-flight — these should already be true

Before starting this sweep, verify:

- [ ] Phase 1–6 are all committed on `feat/acestep-worker-pool` (or merged to `main` — either works)
- [ ] `acestep_manager.py` is already deleted (Phase 3)
- [ ] New Worker Pool / Model Registry admin panels are shipped (Phase 4)
- [ ] `download_model_on_worker` arq job exists (Phase 5)
- [ ] Worker metrics are integrated into the `/metrics` endpoint (Phase 6)
- [ ] `docs/acestep.md` has been rewritten for the new architecture (Phase 6)
- [ ] Full test suite was green as of the Phase 6 commit

If any of these are false, **stop** — finish the phases first, then come back.

## What this sweep covers

1. Repo-wide grep for legacy symbols in places no single phase's self-review looked
2. `CLAUDE.md` "Known Technical Debt" section update (debt that's been paid)
3. `docs/` consistency check (architecture.md, security.md, acestep.md, testing.md)
4. Frontend final sweep (Phase 4 rewrites the UI, but stale types/stores may linger)
5. `docker-compose.yml` orphaned volumes/secrets/env blocks
6. `pyproject.toml` dead deps (nothing obvious — verify)
7. `scripts/` directory stale helpers
8. `.env` / `.env.example` stale entries (if any)
9. Over-cleaning watch — things that look dead but must stay

## Step-by-step procedure

### Step 1: Repo-wide symbol grep

```bash
cd /home/felix-hummert/git/songmaker

# Deleted Python symbols — should have zero hits outside of plans/ and git history
grep -rn "acestep_manager\|AceStepManager\|generate_single\|_run_single_generation" \
  --include="*.py" --include="*.md" --include="*.yml" --include="*.yaml" \
  --include="*.toml" --include="*.sh" --include="*.ts" --include="*.svelte" \
  --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=_models \
  --exclude-dir=.git --exclude-dir=plans \
  .

# Deleted constants — should be zero hits everywhere
grep -rn "ACESTEP_PORT\|ACTIVE_MODEL_REDIS_KEY\|ACESTEP_STATUS_REDIS_KEY\|ACESTEP_STATUS_TTL_SECONDS\|ACESTEP_HEALTH_URL_TEMPLATE\|ACTIVE_MODEL_TTL_SECONDS" \
  --include="*.py" --include="*.md" --include="*.yml" --include="*.yaml" \
  --include="*.toml" --include="*.sh" --include="*.ts" --include="*.svelte" \
  --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=_models \
  --exclude-dir=.git --exclude-dir=plans \
  .

# Deleted API endpoints
grep -rn "/api/admin/acestep/\|acestep_status\|acestep_reinitialize\|reinitialize_acestep\|AceStepStatusResponse\|ReinitializeRequest" \
  --include="*.py" --include="*.ts" --include="*.svelte" --include="*.md" --include="*.yml" \
  --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=plans \
  .

# Deleted Redis/state functions
grep -rn "get_active_model\|_publish_acestep_status\|publish_acestep_heartbeat" \
  --include="*.py" --include="*.ts" --include="*.svelte" \
  --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=plans \
  .
```

**Triage each remaining hit into one of four buckets:**

| Bucket | Action |
|---|---|
| Dead code (import, function call, reference) | Delete |
| Stale doc (README, architecture.md, comment in YAML) | Update to reflect new architecture |
| Historical doc (plan files, git commit messages) | Leave alone — that's history |
| Legitimate use (e.g. `acestep_engine.client.AceStepClient` in `acestep_worker/wrapper.py`) | Leave alone |

Note the `--exclude-dir=plans` flag — plan files ARE history and should not be "cleaned". They document the design evolution.

### Step 2: CLAUDE.md technical debt section

Open [CLAUDE.md](../CLAUDE.md), find the `## Known Technical Debt` section, and audit every entry:

**Debt entries that MUST be removed** (paid by the worker pool implementation):

- **`AceStepManager.switch_model` is single-user / single-GPU debt.** The entire paragraph describing `switch_model` as throwaway code. The state machine, `_switch_lock`, `_active_config_path`, and verification + rollback in `acestep_manager.py` no longer exist. Delete the whole bullet.

**Debt entries that MAY need updating:**

- **`Claude CLI bind mounts in docker-compose.yml`** — unrelated, leave alone
- **`WorkerSettings.redis_settings` is resolved at import time`** — unrelated, leave alone
- **`CLAUDE_CHAT_MODEL` and `CLAUDE_SCORING_MODEL`** — unrelated, leave alone
- **`Redis is authoritative for session expiry`** — unrelated, leave alone
- **`Scorer model caches are module-level globals`** — unrelated, leave alone
- **`create_job_with_rate_limit()` and `unique_album_id()`** — unrelated, leave alone
- **`VRAM verification`** — unrelated, leave alone
- **`slugify()` uses `python-slugify`** — unrelated, leave alone
- **`Backup/restore requires both DB and audio files`** — unrelated, leave alone
- **`Trust boundaries: subprocesses share OS user`** — may need a mention of the new worker containers; update to note acestep-worker subprocess isolation
- **`Seed reproducibility requires `use_random_seed: false`**`— unrelated, leave alone
- **`Claude CLI `_DISALLOWED_TOOLS` is a denylist`** — unrelated, leave alone

**Debt entries that MAY be ADDED** (honest accounting of new debt, if any):

- Shared-secret internal token for worker↔control-plane auth (documented in `docs/security.md`); mTLS / per-worker tokens is the future hardening path. **Add as a debt entry if it's not already.**
- Single ACE-Step worker running as a subprocess inside the acestep-worker container (the same "subprocess inside a container" pattern survives at the worker level — but now it's scoped to one container per GPU instead of baked into the music-worker). **Note: this is acceptable single-node debt and is explicitly called out in the parent plan. Add a debt entry if going multi-node is on the horizon.**

**Verify the file is internally consistent** after editing. Read the whole "Known Technical Debt" section end-to-end.

### Step 3: `docs/` consistency check

Files touched across phases:
- `docs/security.md` — Phase 2 (internal token, trust boundary)
- `docs/architecture.md` — Phase 3 (cutover diagram)
- `docs/acestep.md` — Phase 6 (operator-facing rewrite)
- `docs/testing.md` — may still reference `test_acestep_manager.py`

**Procedure:**

1. **`docs/testing.md`** — grep for `test_acestep_manager`, `AceStepManager`, `generate_single`. Remove any references. The test file is deleted.

2. **`docs/security.md`** — read the Phase 2 worker-pool section. Verify it still accurately describes the trust model after Phase 3–6 changes. If Phase 6 added anything to the internal API (restart endpoint, metrics), document it here.

3. **`docs/architecture.md`** — read the Phase 3 worker pool diagram. Verify it matches the actual architecture after Phases 4–6 (no stale mentions of "will be added in Phase N" that should now be "is implemented").

4. **`docs/acestep.md`** — read the Phase 6 rewrite. Check for:
   - "Coming in Phase N" or "TODO" markers that should now reference actual features
   - Broken cross-links (`[see X.md#Y]` where Y got renamed)
   - References to the old flow that survived the rewrite

5. **Cross-link check:** grep all of `docs/` for `[`.*`]` patterns and verify each link resolves:
   ```bash
   grep -rn "\[.*\](.*\.md" docs/ | grep -v "^Binary"
   ```

### Step 4: Frontend final sweep

Phase 4 rewrote the admin tab into Worker Pool + Model Registry panels. Verify nothing stale remains:

```bash
grep -rn "acestep_status\|AceStepStatus\|acestep_reinitialize\|ReinitializeRequest\|getAceStepStatus\|reinitializeAceStep" \
  frontend/src/ --exclude-dir=node_modules --exclude-dir=.svelte-kit
```

Expected: zero hits. Any remaining hit is a stale reference — delete.

**Also check:**

- **`frontend/src/lib/api/types.ts`** — regenerated by `scripts/generate_types.py` during Phase 2/3/4/5. Should be auto-consistent, but `grep AceStepStatusResponse` on it anyway as a sanity check.
- **`frontend/src/lib/stores/`** — any store named `acestep` or subscribing to deleted endpoints?
- **`frontend/src/routes/`** — any admin route still rendering a stale ACE-Step status widget?
- **`frontend/src/lib/api/admin.ts`** — should have `listWorkers`, `getRegistry`, `loadModelOnWorker`, `evictModelOnWorker`, maybe `restartWorker`; should NOT have `getAceStepStatus` or `reinitializeAceStep`.
- **Svelte components importing from `admin.ts`** — grep for `from "$lib/api/admin"` and verify each imported symbol still exists.

Run `pnpm check` and `pnpm lint` after any edits — catches unused imports TypeScript would flag.

### Step 5: `docker-compose.yml` orphaned entries

Open `docker-compose.yml` and verify:

- **`secrets:` block (top-level)** — `hf_token` is only referenced by `songmaker-scoring-worker` build (music-worker stripped this in Phase 3; acestep-worker never used secrets, it reads `HF_TOKEN` from env). Verify the secret is still used by at least one service.
- **`volumes:` block (top-level)** — every volume has at least one service mounting it. Orphaned volumes are stale.
- **`songmaker-music-worker.environment:`** — should NOT have `ACESTEP_API_HOST`, `ACESTEP_API_PORT`, `HF_TOKEN`. Should have `SONGMAKER_INTERNAL_TOKEN`.
- **`songmaker-music-worker.volumes:`** — should NOT mount `./_models/acestep`. Should mount `audiofiles:/app/data/audio`.
- **`songmaker-music-worker.deploy.resources.devices:`** — should NOT reserve GPU.
- **`songmaker-acestep-worker-0:`** — should have GPU reservation, `./_models/acestep:/app/_models/acestep`, `audiofiles:/app/data/audio`, `HF_TOKEN`, `HF_HUB_DISABLE_XET=1`, `SONGMAKER_INTERNAL_TOKEN`, `REDIS_URL`, `CONTROL_PLANE_URL`, `WORKER_ID`, `WORKER_HOST`, `WORKER_PORT`, `GPU_ID`, `VRAM_BUDGET_GB`.
- **`depends_on:` chains** — music-worker no longer depends on ACE-Step weights being present at startup. The acestep-worker depends on redis being healthy (for heartbeat) and possibly songmaker-web (for registration).

### Step 6: `pyproject.toml` dead deps

```bash
cat pyproject.toml | grep -A 20 "optional-dependencies"
```

Verify each extra's deps are still used:

- **`server`** — used by the web container; verify FastAPI/SQLAlchemy/etc. all still imported somewhere in `src/songmaker_cli/`
- **`scoring`** — unchanged, not touched by worker pool work
- **`whisper`** — unchanged
- **`claude`** — unchanged
- **`acestep-worker`** — added in Phase 1 (`fastapi`, `uvicorn`, `redis[hiredis]`, `huggingface_hub`). Verify all four are imported somewhere in `src/acestep_worker/`
- **`dev`** — unchanged

Also check the **core dependencies** (non-extra):

- `httpx` — used by scheduler, registry_client, admin_api; verify still imported
- `cyclopts` — unchanged (CLI)
- `pyloudnorm` — scoring, unchanged

Run `uv sync --extra server --extra acestep-worker --extra dev` as a smoke test; any dep resolution errors surface here.

### Step 7: `scripts/` directory

```bash
grep -rn "acestep_manager\|AceStepManager\|ACESTEP_API_HOST\|ACESTEP_API_PORT\|ACESTEP_PORT" scripts/
```

Expected legitimate hits:
- `scripts/download_models.sh` — may reference `HF_TOKEN`, config paths; leave as-is (CLI escape hatch per parent plan)

Expected stale hits (delete):
- Any local dev helper that manually starts the old ACE-Step subprocess inside the music-worker context
- Any script that greps for `ACESTEP_STATUS_REDIS_KEY` or publishes to it

### Step 8: `.env` / `.env.example` check

```bash
find . -maxdepth 2 -name "*.env*" -not -path "./.git/*" -not -path "./.venv/*"
```

For each `.env*` file found:
- Grep for `ACESTEP_API_HOST`, `ACESTEP_API_PORT`, `ACTIVE_MODEL_REDIS_KEY` — update or remove
- Add `SONGMAKER_INTERNAL_TOKEN` as an example value if not present
- Add `ACESTEP_WORKER_VRAM_GB` and `ACESTEP_WORKER_CONTROL_PLANE_URL` as example values (referenced in docker-compose.yml)
- `.server.env` itself is gitignored — don't commit its contents, just ensure any `.env.example` or `README` env var documentation is current

### Step 9: Alembic migrations sanity check

**Do NOT delete or edit any migration file.** Migrations are immutable once shipped.

Just verify:

```bash
ls src/songmaker_cli/db/migrations/versions/ | sort
alembic heads
alembic current  # if DB is set up
```

Expected: the migration chain is linear, one head, and includes both `b1c3f4a90210_add_available_models_table.py` (Phase 2 dependency) and `a7b8c9d0e1f2_add_acestep_workers.py` (Phase 2 addition). No orphaned or duplicate revisions.

If `alembic heads` shows more than one head, something went wrong during Phase 2 or Phase 3 — stop and investigate before continuing cleanup.

### Step 10: Final verification

```bash
# Lint
uv run ruff check src/ tests/ acestep_worker/

# Full test suite (same ignore set as the rest of the plan)
uv run pytest tests/ --ignore=tests/test_scorers.py --ignore=tests/test_scorers_extended.py -q

# Frontend
cd frontend && pnpm check && pnpm lint && pnpm test && cd ..

# Type sync
python scripts/generate_types.py
git diff frontend/src/lib/api/types.ts  # expect no diff
```

All four must pass with zero failures.

### Step 11: Plan file status updates (optional)

Open [plans/acestep-worker-pool.md](acestep-worker-pool.md) and — if desired — add a short header note at the top indicating the plan has been fully implemented, with commit SHAs for each phase:

```markdown
> **STATUS: IMPLEMENTED** — All 7 phases shipped on `feat/acestep-worker-pool` and merged to `main`.
> - Phase 1: c416194
> - Phase 2: 275518c
> - Phase 3: <sha>
> - Phase 4: <sha>
> - Phase 5: <sha>
> - Phase 6: <sha>
> - Phase 7 (cleanup): <this commit's sha>
```

This is optional — plan files are historical records, and "this plan was shipped" is already implied by the commit history. But a single-line header makes it obvious to future readers scanning the `plans/` directory that this is a completed initiative, not a pending design.

**Don't delete the sub-plan files.** `plans/acestep-worker-pool-phase2-subplan.md`, `-phase3-subplan.md`, and this `-phase7-subplan.md` are the design record. Future refactors will want to know why decisions were made. Leave them.

## What NOT to touch (over-cleaning watch)

These look stale but must stay. Over-cleaning is worse than under-cleaning because it breaks things:

- **`src/acestep_engine/`** — still used by both music-worker (for `AceStepConfig`) and acestep-worker (for `AceStepClient`). Engine package, independent of the worker pool.
- **`src/acestep_engine/constants.py`** — `MODEL_CONFIG_PATHS` is used by multiple modules. Single source of truth.
- **`available_models` PG table + `AvailableModel` ORM model** — Phase 2 decided to keep this table as the admin's `is_active` allow-list. Still referenced.
- **`scripts/download_models.sh`** — CLI escape hatch per parent plan. Useful for fresh installs, CI, and bootstrapping.
- **`Dockerfile.worker`** — unchanged in Phase 3. Shared between `songmaker-music-worker` and `songmaker-scoring-worker`. Touching it would break the scoring worker.
- **Alembic migration files** — never delete, never rename, never edit committed migrations. Even if the table was later dropped by another migration.
- **`plans/*.md` files** — all of them, including superseded ones (`multi-model-routing.md`) and sub-plans (`-phase1-subplan.md` etc.). They're history.
- **Memory files in `~/.claude/projects/.../memory/`** — not project code, not in scope for repo cleanup. The memory system is operational context.
- **`src/songmaker_cli/api_models/settings.py`** — only `AceStepStatusResponse` and `ReinitializeRequest` should have been deleted. Everything else in that file (presets, defaults, chat, rate limits) is unrelated.
- **`src/acestep_worker/progress.py`** — moved here in Phase 3, used by the worker. Not dead code despite the small file size.
- **`HF_TOKEN` environment variable** — still used by scoring-worker (whisper/audiobox downloads) AND by acestep-worker (model downloads via Phase 5). Keep in compose globally, just verify it's removed from the music-worker's env block specifically.

## Commit strategy

**One commit, clear message.** Something like:

```
chore(acestep-worker): Phase 7 — cleanup sweep

Cross-cutting cleanup after Phases 1–6 of the worker pool plan
have shipped. Deletions and doc updates only, no new features.

- CLAUDE.md: remove switch_model debt entry (paid by Phase 3)
- docs/{testing,security,architecture,acestep}.md: consistency pass,
  cross-link verification
- frontend: remove lingering stale imports from admin.ts cleanup
  (caught by pnpm check after Phase 4)
- docker-compose.yml: verify no orphaned volumes/secrets
- scripts/: remove <stale dev helper> (was referencing
  ACESTEP_API_HOST before cutover)
- .env.example: drop ACTIVE_MODEL_REDIS_KEY, add
  SONGMAKER_INTERNAL_TOKEN / ACESTEP_WORKER_* examples
- plans/acestep-worker-pool.md: add IMPLEMENTED status header

Full suite + ruff + pnpm check all green.
```

Adjust the bullet list based on what was actually cleaned.

**Do NOT bundle this with anything else.** No new features, no refactors, no unrelated fixes. Just the cleanup sweep. Makes review easy.

## Verification checklist (before pushing)

- [ ] All grep commands in Steps 1, 4, 7 return zero hits (outside of `plans/` and expected legitimate uses)
- [ ] CLAUDE.md "Known Technical Debt" section reads cleanly, no references to deleted code
- [ ] `docs/testing.md` has no references to deleted test files
- [ ] `docs/acestep.md`, `docs/architecture.md`, `docs/security.md` are internally consistent and match the actual code
- [ ] Frontend `pnpm check` passes with zero errors
- [ ] `docker-compose.yml` services boot in the test environment (if practical): `docker compose config` at minimum
- [ ] `uv sync --extra server --extra acestep-worker --extra dev` succeeds with no resolution errors
- [ ] Alembic heads is single (no branching migrations)
- [ ] Full backend test suite passes with same ignore set as Phase 6
- [ ] Frontend tests pass
- [ ] `scripts/generate_types.py` produces no diff (types are in sync)
- [ ] The cleanup commit is one self-contained commit (not bundled with other work)

Push to `origin/feat/acestep-worker-pool` (or `main` if already merged). Done.

## Quick context for the agent running this sweep

If you're an agent picking this up cold:

1. Read `CLAUDE.md` for project conventions
2. Read [acestep-worker-pool.md](acestep-worker-pool.md) (parent plan) for context
3. Read this file
4. Run the pre-flight check at the top — verify all 6 phases are shipped
5. Execute Steps 1–10 in order
6. Handle each grep hit according to the triage buckets
7. Run verification checklist
8. Commit + push

**Do not add scope.** This is a cleanup sweep, not a refactor. If you find a real bug during the sweep, note it as a follow-up task — don't fix it in this commit.

**Do not delete historical records.** Plan files, sub-plan files, migration files, and commit history are the design record. Touching them is worse than leaving stale stuff behind.

**Time budget:** 1–2 hours. If you're past 3 hours, something is wrong — stop and ask the user.
