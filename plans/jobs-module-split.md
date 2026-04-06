# Split `jobs.py` (god module)

> **Status: READY** — Highest-blast-radius file in the project. Every job runs through it; every failure mode passes through it. A second contributor will be afraid to touch it.
>
> **Triggers to revisit / deprioritize:**
> - If `multi-model-routing.md` is about to ship, do *that* first — it changes job dispatch and you don't want to refactor `jobs.py` twice.
> - If you're not actively touching `jobs.py` for a feature in the next month, this can wait. Pure debt repayment, no user-visible value.

## Problem

[`src/songmaker_cli/jobs.py`](../src/songmaker_cli/jobs.py) is **637 lines** mixing every job-related concern:

- Generation orchestration (`run_generation_job`, `_run_single_generation`, `_finalize_generation_job`, `_build_generation_context`, `_load_song_meta`, `_load_preset_params`, `_apply_task_overrides`, `_resolve_raw_wav`, `_copy_to_tmp`)
- Scoring orchestration (`run_scoring_job`)
- ACE-Step model setup / mode switching (touched implicitly via `AceStepManager` calls)
- Progress callbacks (`_make_generation_progress_callback`, `_parse_step_fraction`)
- Heartbeat updates (`_touch_heartbeat`)
- Job status updates with retry (`_update_job`)
- Error sanitization (`_sanitize_error`)
- Temp file cleanup (`_cleanup_orphaned_files`)

**16 top-level functions in one file.** Every new job type means touching this file. Every failure mode passes through `_update_job` / `_touch_heartbeat`. The B1/B6 silent-swallow bugs in the architecture review lived here.

## Goal

Three files, each with one clear job. No behavior changes — pure structural refactor.

```
src/songmaker_cli/jobs/
├── __init__.py        # re-exports run_generation_job, run_scoring_job
├── _runtime.py        # shared: _update_job, _touch_heartbeat, _sanitize_error
├── generation.py      # run_generation_job + all generation helpers
└── scoring.py         # run_scoring_job
```

`jobs.py` becomes a deprecation shim re-exporting from `jobs/` for one release, then deleted. (Or skip the shim — `arq` job names are configured by string in `WorkerSettings.functions`, so callers don't import these directly. Verify before deciding.)

## File breakdown

### `jobs/_runtime.py` (~80 lines)

Shared infrastructure used by both job types:

| Symbol | From | Why shared |
|---|---|---|
| `_sanitize_error` | jobs.py:49 | Both jobs call it on exception paths |
| `_update_job` | jobs.py:599 | Both jobs commit terminal state via this |
| `_touch_heartbeat` | jobs.py:617 | Both jobs ping via this |
| `_cleanup_orphaned_files` | jobs.py:630 | Generation uses it; scoring may grow to need it |

These are the only functions that *must* be shared. Everything else belongs to one job type or the other.

### `jobs/generation.py` (~430 lines)

Owns:

- `run_generation_job` (entry point)
- `_run_single_generation`
- `_finalize_generation_job`
- `_build_generation_context`
- `_load_song_meta`
- `_load_preset_params`
- `_apply_task_overrides`
- `_resolve_raw_wav`
- `_copy_to_tmp`
- `_make_generation_progress_callback`
- `_parse_step_fraction`

Imports from `jobs._runtime`. Imports `AceStepManager` for model switching.

### `jobs/scoring.py` (~110 lines)

Owns:

- `run_scoring_job`

Imports from `jobs._runtime`. Imports the scorer subprocess manager.

### `jobs/__init__.py` (~10 lines)

```python
from songmaker_cli.jobs.generation import run_generation_job
from songmaker_cli.jobs.scoring import run_scoring_job

__all__ = ["run_generation_job", "run_scoring_job"]
```

## Order of operations

Each step is independently committable and verifiable. Run `pytest tests/test_jobs.py tests/test_scoring_pipeline.py -q` after each step.

1. **Create `jobs/__init__.py`, `jobs/_runtime.py`** — move `_sanitize_error`, `_update_job`, `_touch_heartbeat`, `_cleanup_orphaned_files`. Replace with re-imports in old `jobs.py`. Tests must still pass.
2. **Create `jobs/scoring.py`** — move `run_scoring_job` and its imports. Re-export from `jobs.py` for now. Tests pass.
3. **Create `jobs/generation.py`** — move all remaining generation code. Re-export from `jobs.py`. Tests pass.
4. **Delete the old `jobs.py`** — replace with `jobs/__init__.py`. Update `WorkerSettings.functions` references in `music_worker.py` and `scoring_worker.py` to point at `songmaker_cli.jobs.generation:run_generation_job` etc. Run full suite.
5. **Update tests** — `tests/test_jobs.py` is currently 559 lines testing both job types together. Optional follow-up: split into `test_generation_job.py` + `test_scoring_job.py` mirroring the new structure. Not required for the refactor PR.

## Verification

After each step:

```bash
ruff check src/ tests/
pytest tests/test_jobs.py tests/test_scoring_pipeline.py tests/test_music_worker.py tests/test_scoring_worker.py -q
```

After step 4:

```bash
pytest tests/ -n auto -q --cov=songmaker_cli --cov-report=term-missing
```

Coverage on `jobs/` must match or exceed pre-refactor coverage on `jobs.py`. No coverage regression allowed.

## Constraints

- **No behavior changes.** This is a structural refactor only. If a test breaks, the refactor is wrong, not the test.
- **No new error handling.** The B1 swallow fixes are already shipped. Don't add anything new "while we're here."
- **No new abstractions.** Don't introduce a `JobRunner` base class or `Job` ABC. The two job types share `_runtime.py` and that's it. If they grow more shared logic later, abstract then.
- **No comments.** Per CLAUDE.md.
- **Engine isolation must hold.** `jobs/generation.py` may import from `acestep_engine` and `audio_engine`. Neither engine package may import from `jobs/`.

## Risks

- **arq function references.** `WorkerSettings.functions` is a list of callables. If it points at `songmaker_cli.jobs.run_generation_job` by import, the deprecation shim handles it. If it points at the function object directly, the workers need an updated import path on the same deploy. **Verify before starting** by grepping `WorkerSettings.functions`.
- **Test fixtures may import from `jobs`.** Find every `from songmaker_cli.jobs import` first; the shim covers them but you should know the surface area.
- **Diff size.** ~600 lines moved across 4 new files. Reviewer must verify file-by-file that nothing was lost. Consider posting a "moved-only, no logic change" diff helper: `git diff -M50% --stat`.

## Success criteria

- `jobs/_runtime.py` ≤ 100 lines, `jobs/scoring.py` ≤ 150 lines, `jobs/generation.py` ≤ 450 lines
- Old `jobs.py` is gone (or is a 10-line shim)
- All existing tests pass without modification (test split is optional follow-up)
- Coverage unchanged or higher on the new files vs old `jobs.py`
- A new contributor can find "where does generation orchestration live?" by reading the directory listing

## Out of scope

- Splitting `tests/test_jobs.py` (optional follow-up)
- Adding new job types (a clean structure makes this easier; don't bundle it)
- Refactoring `AceStepManager` calls (separate concern, see `multi-model-routing.md` triggers)
- Job lifecycle changes / orphan cleanup janitor (deferred — existing recovery covers it)
