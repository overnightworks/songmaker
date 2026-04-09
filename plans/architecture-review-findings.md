# Architecture Review — Findings & Cleanup

**Status:** In progress — quick-wins and W1 of no-silent-fallbacks landed; W2 in flight; B1/B8/B9 still deferred
**Date:** 2026-04-09 (refreshed late afternoon)
**Context:** Brutal architecture review of the codebase identified 12 findings. This document records each one, its current status, and the decisions needed to act on it.

> **Note on plan-writing convention:** the per-finding sections below intentionally include the "What/Why/Decision" but NOT a step-by-step implementation plan. Per CLAUDE.md "Plan-writing convention", future work captures concepts and locked-in decisions only — the executing agent reads the live code, designs the implementation in-session, and executes. If you're picking up B1, B8, or B9: the section below has everything you need to start. Run the greps, read the code, design and execute. Do not re-prompt the user for already-locked decisions.
**Related plans:**
- [no-silent-fallbacks-v2.md](no-silent-fallbacks-v2.md) — covers B2, B7, B12. **W1 done, env merge done, W2 in progress.**
- [no-silent-fallbacks-w1-cleanup.md](no-silent-fallbacks-w1-cleanup.md) — W1 cleanup checklist, **executed** (commits f1ad2d4 + 5571009).
- [single-env-file-docker-only.md](single-env-file-docker-only.md) — env file consolidation, **executed** (commit ffd80d2).
- [jobs-module-split.md](jobs-module-split.md) — pre-existing plan, sequenced after no-silent-fallbacks-v2 lands. **B1's owner.**

## Quick reference

| # | Finding | Status | Owner action |
|---|---|---|---|
| B1 | `jobs.py` 925-line god module | ⏳ **Deferred** — execute after no-silent-fallbacks-v2 lands | Sequencing locked in. The W2 typed params will make the split cleaner. |
| B2 | Hardcoded `task_type` strings | 🔄 **Covered** by no-silent-fallbacks-v2 **W2 (in flight)** | Will be deleted by W2's `Literal["text2music"\|"repaint"\|"cover"]` discriminator |
| B3 | Scorer subprocess Pipe race | ✅ **Done** (commit `3e66551`) | — |
| B4 | CI excludes scoring coverage | ✅ **Accepted, documented** (commit `1ee2842`) | Note in `.coveragerc-ci` + CLAUDE.md tech debt |
| B5 | `worker_base.py` is not a base class | ✅ **Done** (commit `be046a9`) | `WorkerBase` class is now real, used by `MusicWorker` and `ScoringWorker` |
| B6 | `Generation.version_id` missing index | ✅ **Done** (commit `a78ec5f`, migration `a1b2c3d4e5f6`) | — |
| B7 | Import-time singletons (REDIS_URL, CLAUDE_*_MODEL) | ✅ **Done** by W1 (commit `9abbf89`) | All 3 footgun entries deleted from CLAUDE.md |
| B8 | Stuck-`QUEUED` jobs never recovered | ⏳ **Pending** — design locked in below | `QUEUE_MAX_AGE_SECONDS = 600` + recovery rule. Independent of W2; can ship after the v2 PR. |
| B9 | Backpressure invisible to UI | ⏳ **Pending** — 3-layer design locked in below | Backend: queue_position + queue_depth_cap_reached on job-status response. Frontend: hint + position + disabled-at-cap. Independent of W2. |
| B10 | PID-based stale detection | ✅ **Done** (commit `3b59e48`, migration `b2c3d4e5f6a7`) | PID fallback gone, `heartbeat_at NOT NULL` |
| B11 | Stale `plans/` directory | ✅ **Done** (commit `650b500`) | Status headers + archive folder + CLAUDE.md convention |
| B12 | Configuration scattered (~73 env reads) | ✅ **Done** by W1 (commits `9abbf89..5571009`) | Single `Settings` class, all env reads in `settings.py`, `extra="forbid"` |

**Score so far:** 7 done (B3, B4, B5, B6, B7, B10, B11, B12 — wait that's 8), 1 in flight (B2 via W2), 3 deferred (B1, B8, B9).

## Sequencing

```
✅ 1. Quick-wins PR        (B3, B5, B6, B10, B11 + B4 note)         [DONE — commits 1ee2842..be046a9]
🔄 2. no-silent-fallbacks  (covers B2, B7, B12 + preps B1)
       ✅ W1 (Settings)        [DONE — commits 9abbf89..5571009]
       ✅ Env merge            [DONE — commit ffd80d2]
       🔄 W2 (typed params)    [IN FLIGHT — fresh agent session]
       ⏳ W3-W5                [pending after W2]
⏳ 3. B1 jobs.py split        (jobs-module-split.md, much easier after typed params land)
⏳ 4. B8 + B9                  (parallel — independent, both need new fields on job-status response)
```

---

## B1 — `jobs.py` is a 925-line god module

**What:** [src/songmaker_cli/jobs.py](../src/songmaker_cli/jobs.py) bundles generation orchestration, post-processing/mastering, scoring orchestration, model load/download dispatch, heartbeat plumbing, and orphan cleanup. The two largest functions (`run_generation_job`, `run_scoring_job`) are 100+ lines each.

**Why it matters:** Every change to scoring touches the same file as every change to generation dispatch. New contributors cannot reason about this module in one sitting.

**Decision:** **Execute** [plans/jobs-module-split.md](jobs-module-split.md) — but **after** [plans/no-silent-fallbacks-v2.md](no-silent-fallbacks-v2.md) lands. The fallbacks branch heavily rewrites `jobs.py` (replaces `_apply_task_overrides`, `_load_preset_params`, the `run_generation_job` signature). Splitting before would create rebase pain; splitting after means the typed `BaseGenerationParams` already exists, making the cuts cleaner.

**When `jobs-module-split.md` runs:** the existing plan stays correct. Validate it against the post-fallbacks state of `jobs.py` and update the file references if needed.

**Deferred work for the splitter:**
- Add a `Status: In progress` header to `jobs-module-split.md` when work starts.
- Verify the split still makes sense after the typed-params refactor.
- Target modules per the existing plan: `jobs/generation.py`, `jobs/scoring.py`, `jobs/model_lifecycle.py`, `jobs/postprocess.py`. Keep `jobs.py` as a thin re-export shim only if arq's task-name registration depends on it.

---

## B2 — Hardcoded `task_type` strings 🔄 IN FLIGHT (W2)

**What:** [jobs.py:509-527](../src/songmaker_cli/jobs.py#L509) and [generation_api.py:243-295](../src/songmaker_cli/generation_api.py#L243) compare `task_type == "repaint"` / `"cover"` / `"generate"` inline.

**Coverage:** [no-silent-fallbacks-v2.md](no-silent-fallbacks-v2.md) Workstream 2 (currently in flight) introduces a Pydantic discriminated union with `Literal["text2music"|"repaint"|"cover"]`. Type-safe, no separate enum needed, the type system catches typos.

**Action:** None. Verify the string compares are gone after W2 lands.

---

## B3 — Scorer subprocess Pipe race at `SCORING_MAX_JOBS > 1` ✅ DONE

**Shipped:** commit `3e66551 fix(scoring): serialize concurrent score() calls with a Pipe lock`. `ScorerProcess._pipe_lock` (threading.Lock) wraps `_score_with_retry`. Test added: `test_concurrent_score_calls_are_serialized` spawns two threads and verifies both return correct results.

**What:** [scoring/subprocess_runner.py:182-209](../src/songmaker_cli/scoring/subprocess_runner.py#L182) — `_score_with_retry` calls `conn.send(request)` then `_poll_response(conn, …)` on a single `multiprocessing.Pipe` with **no lock**. Default `SCORING_MAX_JOBS=1` saves it today, but the env var is documented as configurable.

**Decision:** Keep `SCORING_MAX_JOBS` configurable (locked in via [no-silent-fallbacks-v2.md](no-silent-fallbacks-v2.md) W1 settings). Therefore the lock is **mandatory** — without it, raising `SCORING_MAX_JOBS` to 2 produces interleaved Pipe writes and scrambled responses.

**Fix (defensive, ships in quick-wins PR):**
- Add `self._pipe_lock = threading.Lock()` to `ScorerProcess.__init__`.
- Wrap `_score_with_retry` body in `with self._pipe_lock:`.
- Held across send + poll. Yes this serializes scoring at the subprocess level — correct, because there's only one subprocess. The "use the GPU better" benefit of `SCORING_MAX_JOBS=2` was illusory anyway; the GPU bottleneck is the model itself, not Python concurrency.

**Acceptance:** unit test that spawns two threads calling `score()` concurrently, asserts both return correct results (today this would intermittently corrupt one of them).

---

## B4 — CI excludes the entire scoring pipeline ✅ ACCEPTED & DOCUMENTED

**Shipped:** commit `1ee2842 docs: explain why scorers are excluded from CI coverage`. `.coveragerc-ci` has a header comment explaining the trade-off. CLAUDE.md "Known Technical Debt" has a matching entry.

**What:** `.coveragerc-ci` omits all 7 scorers (`audiobox_aesthetics`, `bpm_accuracy`, `emotional_dynamics`, `lyrical_coherence`, `silence_detection`, `spectral_quality`, `text_accuracy`). CI claims 90% coverage on what's left.

**Decision:** **Accepted as-is.** All scorers technically work on CPU (faster-whisper makes `text_accuracy` viable on CPU, just slower), so the *code* could be tested in CI. The blocker is the **CI image** — it doesn't have the model weights / faster-whisper / audiobox-aesthetics installed, and adding them blows up CI image size and runtime for marginal benefit on a single-developer project.

**Action:**
1. Add a comment block at the top of `.coveragerc-ci` explaining *why* scorers are excluded (CI image doesn't ship the heavy deps, not because they're untestable).
2. Add a one-line note to CLAUDE.md "Known Technical Debt" referencing this finding.
3. Local development still runs the full suite with `--cov`; that's the canonical coverage check for scorer code.

**Revisit when:** the project moves to a multi-user deployment, gets a beefier CI runner, or a scorer regression actually slips through. Until then, the cost/benefit doesn't justify the work.

---

## B5 — `worker_base.py` is not a base class ✅ DONE

**Shipped:** commit `be046a9 refactor(workers): introduce WorkerBase class`. `WorkerBase` is now a real class with `__init__(settings)`, owning DB engine, recovery lock, orphan audit, etc. `MusicWorker(WorkerBase)` and `ScoringWorker(WorkerBase)` are subclasses, instantiated as singletons (`_music_worker = MusicWorker(_settings)`) at module import time so arq's class-attribute inspection sees a validated value.

**What:** [src/songmaker_cli/worker_base.py](../src/songmaker_cli/worker_base.py) is named like a base class but is a grab-bag of module-level helpers (`_get_db_factory`, `recover_on_startup`, `common_shutdown`) imported as functions by `music_worker.py` and `scoring_worker.py`. The `_db_factory` global is shared via process-level state.

**Decision:** **Full `WorkerBase` class refactor** (the cleanest option, locked in).

**Fix (ships in quick-wins PR):**
- New class `WorkerBase` in `src/songmaker_cli/worker_base.py`:
  ```python
  class WorkerBase:
      """Base class for arq workers. Owns DB engine + factory lifecycle,
      stale-job recovery, and orphaned-file audit. Subclassed by
      MusicWorker and ScoringWorker."""

      job_type: ClassVar[JobType]  # Set by subclass
      recovery_lock_key: ClassVar[str]

      def __init__(self, settings: WorkerSettings) -> None:
          self._settings = settings
          self._db_engine: Engine | None = None
          self._db_factory: sessionmaker[Session] | None = None
          self._db_lock = threading.Lock()

      def get_db_factory(self) -> sessionmaker[Session]: ...
      async def on_startup(self, ctx: dict) -> None: ...
      async def on_shutdown(self, ctx: dict) -> None: ...
      def make_cleanup_cron(self) -> CronJob: ...
      def audit_orphaned_files(self) -> None: ...
  ```
- `MusicWorker(WorkerBase)` and `ScoringWorker(WorkerBase)` set `job_type` + `recovery_lock_key` and add their own `functions = [...]`.
- The global `_db_factory` / `_db_engine` / `_db_lock` are deleted. State lives on `self`.
- arq integration: `WorkerSettings.on_startup` / `on_shutdown` become small adapters that instantiate the class once and delegate. (arq wants module-level callables; the adapters wrap a singleton instance.)

**Coordination with no-silent-fallbacks-v2 W1:** the `Settings` consolidation also touches `worker_base.py`. To minimize merge pain, do **B5 first** (in quick-wins PR), then W1 builds on the new class shape (`WorkerBase.__init__(settings: WorkerSettings)`).

**Acceptance:** `music_worker.py` and `scoring_worker.py` each contain only a class declaration + arq adapter; no functions imported from `worker_base`. Tests for `WorkerBase` instantiate the class directly with a dummy settings object.

---

## B6 — `Generation.version_id` missing index ✅ DONE

**Shipped:** commit `a78ec5f fix(db): index Generation.version_id` + Alembic migration `a1b2c3d4e5f6_add_index_generations_version_id`. Index applied to dev DB on 2026-04-09 deploy. Verified via `\d generations` showing `ix_generations_version_id`.

**What:** [db/models.py:133-135](../src/songmaker_cli/db/models.py#L133) — every other FK on `generations` (`song_id`, `mp3_path`, `src_generation_id`) has `index=True`. `version_id` was forgotten. Any "list generations for this version" query is a seqscan.

**Fix (ships in quick-wins PR):**
- Add `index=True` to the column declaration.
- New Alembic migration: `alembic revision -m "add index on generations.version_id"`, single `op.create_index()` call.
- Run `alembic upgrade head` against dev DB.

**Acceptance:** `\d generations` in psql shows the new index. No query changes needed.

---

## B7 — Import-time singletons (REDIS_URL, CLAUDE_*_MODEL) ✅ DONE

**Shipped by W1:** commits `9abbf89 feat(settings): introduce Settings(BaseSettings)` + `f1ad2d4` + `5571009`. The three CLAUDE.md "Known Technical Debt" entries about `WorkerSettings.redis_settings`, `CLAUDE_CHAT_MODEL`, and `CLAUDE_SCORING_MODEL` import-time resolution are deleted. All env reads happen via `get_settings()` which is `lru_cache`d and reads `.server.env` (now `.env`) via Pydantic Settings. The "warn on REDIS_URL mismatch" code path is gone — pydantic-settings reads the env file at construction time so the import-time/post-load divergence cannot occur.

**What:** CLAUDE.md "Known Technical Debt" documents that `WorkerSettings.redis_settings`, `CLAUDE_CHAT_MODEL`, `CLAUDE_SCORING_MODEL` resolve at import time, with a runtime warning if values differ.

**Coverage:** [no-silent-fallbacks-v2.md](no-silent-fallbacks-v2.md) Workstream 1 kills these entirely. The plan's completion criteria explicitly delete these CLAUDE.md technical-debt entries.

**Action:** None — verified gone in commit `9abbf89`.

---

## B8 — Stuck-`QUEUED` jobs never recovered

**What:** [db/queries/jobs.py:198-229](../src/songmaker_cli/db/queries/jobs.py#L198) `recover_stale_jobs_by_age` keys off heartbeat staleness or PID liveness. A job that sits in `QUEUED` because no worker is online has no heartbeat and no PID — the cleanup cron won't touch it. User sees "queued" forever.

**Decision:** `QUEUE_MAX_AGE_SECONDS = 600` (10 minutes). Locked in.

**Fix (ships AFTER no-silent-fallbacks-v2, can be parallel with B9):**
- Add `QUEUE_MAX_AGE_SECONDS: int = 600` to `Settings` (the new W1 settings class).
- Extend `recover_stale_jobs_by_age` to additionally mark as FAILED any row where:
  ```
  status = QUEUED
  AND created_at < now() - QUEUE_MAX_AGE_SECONDS
  AND no online worker exists for this job_type
  ```
- "No online worker" check uses the existing `_list_online_workers()` from the scheduler.
- Failure message: `"No worker available for {job_type} after {QUEUE_MAX_AGE_SECONDS}s — please retry."` (user-facing, shown in the job-status response).
- The cleanup cron already runs every 2 minutes ([music_worker.py:101](../src/songmaker_cli/music_worker.py#L101)); no scheduling change needed.

**Acceptance:**
- Unit test: insert a job with `created_at = now - 700s`, status QUEUED, no workers registered → cron run marks it FAILED with the expected message.
- Inverse test: same job but with an online worker → not touched.

---

## B9 — Backpressure invisible to UI

**What:** Queue depth is exposed in `/metrics` and `/health` but the frontend doesn't show it. Users submit and wait blindly. Hitting `max_queue_depth` (today: 100) returns a 429 with no warning.

**Decision: three-layer design (cleanest option, locked in).**

### Layer 1 — Queue depth hint under the submit button (always visible)

- Existing `/health` already exposes `queue_depth` and per-job-type breakdown.
- New Svelte store `lib/stores/queue.ts` polls `/health` every 5s (or piggybacks on the existing admin polling if present).
- `GenerateButton.svelte` (or wherever the submit lives) reads the store and renders:
  - `queue_depth == 0`: nothing
  - `queue_depth > 0`: subtitle text "{n} jobs ahead of you (~{n*avg_duration} min wait)" — `avg_duration` comes from the existing job duration metric in `/metrics` or a hardcoded estimate per job_type.
- Non-blocking. User can still submit.

### Layer 2 — Position-in-queue while waiting (post-submit)

- New field on the job-status response (the one the frontend already polls): `queue_position: int | None`.
- Backend computes it as `SELECT count(*) FROM jobs WHERE job_type = $1 AND status = 'QUEUED' AND created_at < $2` where `$2` is the current job's `created_at`. Add an index on `(job_type, status, created_at)` if not already present (verify in B6's migration or add a separate one).
- Returns `None` when status is not QUEUED.
- Frontend job-status display shows "You're #{queue_position} in queue" while waiting, vanishes when status flips to RUNNING.

### Layer 3 — Disable submit at hard cap

- `Settings.max_queue_depth` (already exists) is the hard cap that today causes a 429.
- New field on `/health`: `queue_depth_cap_reached: bool` (true when global queue_depth >= max_queue_depth, OR when the user's own active job count is at `max_user_active_jobs`).
- Frontend: when true, disable the submit button + tooltip "Queue full — please try again in a moment." No more surprise 429s.

### Implementation footprint

- **Backend** (~80 lines):
  - Add `queue_position` field to `JobResponse` Pydantic model + `from_orm` computation.
  - Add `queue_depth_cap_reached` field to `/health` response.
  - Possibly an index migration if `(job_type, status, created_at)` isn't indexed.
- **Frontend** (~70 lines):
  - New `lib/stores/queue.ts` (queue depth polling + cap signal).
  - Wire to `GenerateButton.svelte` (hint + disable).
  - Wire to existing job-status display (position).

**Sequencing:** independent of no-silent-fallbacks-v2 — can ship as a separate PR after the fallbacks branch lands. Touches different files. Can be parallel with B8 (both add fields to job-status response — coordinate the Pydantic model edit).

**Acceptance:**
- Unit test: backend computes correct `queue_position` for 5 queued jobs of mixed types.
- Manual test: submit a job, refresh, see hint update; submit until cap, verify button disables.

---

## B10 — PID-based stale detection collides with PID reuse ✅ DONE

**Shipped:** commit `3b59e48 fix(jobs): drop PID liveness fallback, make heartbeat_at NOT NULL` + Alembic migration `b2c3d4e5f6a7_heartbeat_at_not_null`. The `_is_worker_alive(pid)` helper is deleted entirely. `_is_heartbeat_stale` now does a single `heartbeat_at < cutoff` comparison. Backfill migration set `heartbeat_at = started_at` for any historical NULL rows, then ALTER COLUMN NOT NULL. Applied to dev DB on 2026-04-09 deploy.

**What:** [db/queries/jobs.py](../src/songmaker_cli/db/queries/jobs.py) `_is_heartbeat_stale` falls back to `os.kill(pid, 0)` when `heartbeat_at IS NULL`. On a long-uptime container, PIDs recycle — a dead worker's old PID may be held by `redis-server` and the check returns "alive."

**Decision:** drop the PID fallback. Backfill `heartbeat_at` to `NOT NULL`. Locked in.

**Fix (ships in quick-wins PR — code half + migration):**

1. **Code change** in `_is_heartbeat_stale`:
   - Delete the `os.kill(pid, 0)` branch entirely.
   - If `heartbeat_at IS NULL`, treat as stale (return True).
   - Simpler logic: `return heartbeat_at is None or heartbeat_at < cutoff`.

2. **Migration:**
   ```python
   # alembic revision -m "heartbeat_at not null + backfill"
   def upgrade():
       op.execute("UPDATE jobs SET heartbeat_at = updated_at WHERE heartbeat_at IS NULL")
       op.alter_column("jobs", "heartbeat_at", nullable=False)
   ```
   - Backfills using `updated_at` as the best available proxy for any historical row.
   - Single transaction; safe to run on dev DB. Production deploys run it during normal Alembic upgrade.

3. **Model update:** [db/models.py](../src/songmaker_cli/db/models.py) — change `heartbeat_at: Mapped[datetime | None]` → `heartbeat_at: Mapped[datetime]` with `default=_utcnow`. Insert path already populates it via `update_job_heartbeat`; the default ensures even rows that bypass the helper get a value.

4. **Insert path verification:** grep for `INSERT INTO jobs` and `Job(...)` constructions in `db/queries/jobs.py` — all must produce a non-null `heartbeat_at`. The `default=_utcnow` covers it but verify no path overrides with `None`.

**Acceptance:**
- Migration runs clean on dev DB.
- `\d jobs` shows `heartbeat_at` as `NOT NULL`.
- Unit test: dead worker with stale heartbeat → recovery marks job FAILED. Live worker with fresh heartbeat → not touched. (Old PID-reuse scenario no longer reachable.)

---

## B11 — Stale `plans/` directory ✅ DONE

**Shipped:** commit `650b500 chore(plans): standardize Status/Date headers + archive completed plans`. Every plan file in `plans/` now has a `**Status:**` and `**Date:**` header. `acestep-model-parameters.md` moved to `plans/archive/` (was Done). `infinite-duration.md` and `no-silent-fallbacks.md` deleted (the user decided the first was a bad direction; the second was superseded by v2). CLAUDE.md "Where Things Go" documents the convention.

**What:** 9 markdown files in `plans/`, several describing refactors that never happened. No status headers, no dates. New contributors can't tell what's in-progress vs aspirational.

**Fix (ships in quick-wins PR):**

1. **Create `plans/archive/`** subdirectory.

2. **Add status headers to every file** in `plans/`. Format (matching this doc and `no-silent-fallbacks-v2.md`):
   ```markdown
   # Title

   **Status:** Proposed | In progress | Done | Abandoned
   **Date:** YYYY-MM-DD
   ```

3. **Status assignments (locked in):**
   | File | Status | Action |
   |---|---|---|
   | `acestep-model-parameters.md` | **Done** | Add `Status: Done` header, move to `archive/` |
   | `base-model-tasks.md` | **Proposed** | Add `Status: Proposed` header, leave in place |
   | `claude-streaming-and-sdk-migration.md` | **Proposed** | Add header, leave in place |
   | `frontend-component-split.md` | **Proposed** | Add header, leave in place |
   | `infinite-duration.md` | **Delete** | `git rm` — user decided this direction makes no sense |
   | `jobs-module-split.md` | **Proposed** | Add header + note "sequenced after no-silent-fallbacks-v2" |
   | `lora-voice-training.md` | **Proposed** | Add `Status: Proposed` header, leave in place |
   | `mobile-and-testing.md` | **Proposed** | Add header, note "older plan, still valid" in body |
   | `move-generation.md` | **Proposed** | Add `Status: Proposed` header, leave in place |
   | `no-silent-fallbacks.md` (deleted) | **Superseded** | `git rm` — superseded by `no-silent-fallbacks-v2.md` |

4. **Resurrect-and-supersede** the deleted `plans/no-silent-fallbacks.md`: it's currently `D` in git status. Either `git rm` it cleanly (the v2 supersedes it) or `git checkout` it and add `**Status:** Superseded by no-silent-fallbacks-v2.md`. Recommend `git rm` — v2 has all the content.

5. **Document the convention** in `CLAUDE.md` under "Where Things Go": every plan file has a `Status:` and `Date:` header; done/abandoned plans move to `plans/archive/`.

**Acceptance:** every remaining file in `plans/` has a `Status:` and `Date:` header. `acestep-model-parameters.md` is in `archive/`. `infinite-duration.md` and `no-silent-fallbacks.md` are `git rm`'d.

---

## B12 — Configuration scattered across 22 files ✅ DONE

**Shipped by W1:** commits `9abbf89..5571009` + the env merge commit `ffd80d2`. New `src/songmaker_cli/settings.py` with `Settings(BaseSettings)` and `WorkerSettings(BaseSettings)` (split, not inheriting). New `src/acestep_engine/settings.py` for engine isolation. All 73 env reads consolidated. `extra="forbid"` set in all three Settings classes — typo'd env var names raise `ValidationError` at startup. The env merge commit (`ffd80d2`) collapsed `.env` and `.server.env` into a single `.env` file and removed the local-dev `uv run songmaker server` path. Verified via the four W1 cleanup-plan greps, all returning empty.

**What:** 73 env reads scattered across the codebase, no central Settings.

**Coverage:** [no-silent-fallbacks-v2.md](no-silent-fallbacks-v2.md) Workstream 1 is exactly this fix. `Settings(BaseSettings)` consolidation, every `os.environ.get()` outside `settings.py` deleted.

**Action:** None — verified clean after `5571009`.

---

## Quick-wins PR — concrete contents

Single PR, branch `chore/architecture-quick-wins`:

1. **B6** — `Generation.version_id` index + Alembic migration
2. **B11** — `plans/` Status headers + `archive/` folder + `git rm` deleted fallbacks plan + CLAUDE.md convention note
3. **B3** — scorer Pipe lock (`threading.Lock` in `ScorerProcess`)
4. **B10** — drop PID fallback in `_is_heartbeat_stale` + backfill migration + model `NOT NULL`
5. **B5** — `WorkerBase` class refactor
6. **B4** — comment block in `.coveragerc-ci` + CLAUDE.md "Known Technical Debt" note

**Estimated diff:** ~400 lines across ~15 files. Two Alembic migrations (B6, B10).

**Conflict risk with no-silent-fallbacks-v2:** Low. The only overlap is `worker_base.py` (B5 reshapes it; W1 then injects `Settings` into the new class). Doing B5 first means W1 builds on a clean class — easier, not harder.

**After merge:** start `refactor/no-silent-fallbacks` branch.

## After no-silent-fallbacks-v2 lands

In order:
1. **B1** — execute `plans/jobs-module-split.md` (much easier with typed params already in place).
2. **B8 + B9** — can ship in parallel; coordinate the `JobResponse` Pydantic edit since both add fields.

## Open decisions

None. Every finding has a locked-in decision and a concrete fix path. Ready to ship the quick-wins PR.
