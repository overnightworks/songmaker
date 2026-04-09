# Split `jobs.py` (god module)

**Status:** Proposed
**Date:** 2026-04-09 (concept)
**Sequencing:** Execute **after** [no-silent-fallbacks-v2.md](no-silent-fallbacks-v2.md) lands fully. The fallbacks branch has heavily reshaped `jobs.py`; splitting after means the typed `BaseGenerationParams` and the W3 smell-site fixes are already in, and the cuts are cleaner.

## Problem

`src/songmaker_cli/jobs.py` is the highest-blast-radius file in the project. As of late 2026-04-09 it's around 950 lines and mixes four unrelated concerns: generation orchestration, scoring orchestration, worker model management (`load_model_on_worker` / `download_model_on_worker`), and shared job runtime helpers (`_update_job`, `_touch_heartbeat`, `_sanitize_error`, `_cleanup_orphaned_files`). Every job runs through it. Every failure mode passes through it. New contributors are afraid to touch it.

## Goal

Split into a `src/songmaker_cli/jobs/` package with one file per concern. Old `jobs.py` becomes a thin deprecation shim re-exporting the public entry points so existing imports and `tests/test_jobs.py` patches keep working. **Pure structural refactor — no behavior changes.**

Target shape (the executing agent picks the exact symbol-by-symbol cuts after reading the live code):

```
src/songmaker_cli/jobs/
├── __init__.py            # re-exports public entry points
├── _runtime.py            # _sanitize_error, _update_job, _touch_heartbeat, _cleanup_orphaned_files
├── generation.py          # run_generation_job + all generation helpers + post_process_generation
├── scoring.py             # run_scoring_job
└── model_lifecycle.py     # load_model_on_worker, download_model_on_worker
```

## Locked-in decisions (do NOT re-prompt the user)

- **4 files**, not 3. The original 3-file plan missed `load_model_on_worker` / `download_model_on_worker` (~190 lines combined). They are out-of-band admin tasks, conceptually their own concern, give them their own file.
- **Keep `jobs.py` as a deprecation shim.** Verified safe: workers import from `songmaker_cli.jobs` and `tests/test_jobs.py` patches paths under `songmaker_cli.jobs.X`. The shim covers both.
- **No new abstractions.** No `JobRunner` base class, no `Job` ABC. Files share `_runtime.py` and that's it.
- **No new error handling, no comments, no behavior changes.** This is a pure move-and-rename refactor.
- **`db_factory` injection pattern stays.** `load_model_on_worker` / `download_model_on_worker` take `db_factory` as a keyword-only argument (post-W1 pattern). The MusicWorker wrapper passes `self.get_db_factory()`. Do not regress to module-level `_get_db_factory()` lookup.

## Constraints

- **Engine isolation** (CLAUDE.md "Code Patterns") must hold: `acestep_engine`, `audio_engine`, AND `acestep_worker` may not import from the new `jobs/` package. Verify with `grep -rn "from songmaker_cli\|import songmaker_cli" src/acestep_engine/ src/audio_engine/ src/acestep_worker/` — must return empty after the refactor.
- **Engine packages (acestep_engine, audio_engine) may be imported BY `jobs/generation.py`** — that direction is fine.
- **`tests/test_jobs.py`** has many `patch("songmaker_cli.jobs.X")` calls. The deprecation shim covers them. If you choose to update the patches in the same PR (cleaner end state), expect ~50 path updates.
- **`tests/test_jobs.py` is also a god module** (~1300 lines). Splitting it to mirror the new structure is an **optional follow-up**, not required by the refactor PR.
- **No coverage regression.** New `jobs/` files combined must match or exceed pre-refactor coverage on `jobs.py`.

## First action for the executing agent

Don't trust this plan's symbol lists or line counts — trust the live code. Start with:

```bash
wc -l src/songmaker_cli/jobs.py
grep -n "^def \|^async def \|^class " src/songmaker_cli/jobs.py
grep -rn "from songmaker_cli.jobs import\|songmaker_cli\.jobs\." src/ tests/ | grep -v __pycache__
```

Then write your own real implementation plan for THIS session (with current symbol inventory and a step-by-step move order) and execute it. Use the locked-in decisions and constraints above as the contract — everything else is your call.

## Verification before merging

```bash
ruff check src/ tests/
pytest tests/ -n auto -q --cov=songmaker_cli --cov-report=term-missing
# Live deploy (run in background per CLAUDE.md "Docker" rule):
docker compose up -d --build --wait
docker compose logs songmaker-music-worker | tail -10  # should show "generate worker ready"
docker compose logs songmaker-scoring-worker | tail -10  # should show "score worker ready"
```

## Out of scope

- Splitting `tests/test_jobs.py` (optional follow-up)
- Adding new job types
- Refactoring `AceStepManager` calls
- Job lifecycle changes / orphan cleanup janitor
- Backpressure (B9 in `architecture-review-findings.md`)
