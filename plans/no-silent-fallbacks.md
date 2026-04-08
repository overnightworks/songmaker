# No Silent Fallbacks for Required Configuration

> **Status: PLAN** — Architectural cleanup. Awaiting review.
>
> **Origin:** discovered 2026-04-08 during recovery cleanup. The `available_models` table was wiped by the recovery `restore.sql` TRUNCATE, which broke 3 user-visible features simultaneously: model selector empty, "Failed to save preset", and every new generation silently labeled `model_mode='turbo'` regardless of what was loaded on the worker. **All three are downstream symptoms of one bad pattern**: required configuration falling through to silent defaults at every layer instead of failing loudly at the boundary.

## The principle

> **Validate at boundaries. No silent defaults for required configuration.**
>
> If a value is required for a downstream operation, the layer that accepts it from outside (HTTP request, env var, CLI arg, DB seed) must either:
> 1. **Reject missing input** — raise/422 at the boundary
> 2. **Or use a NAMED constant** as the default and log when the default is taken
>
> Falling through to dict-insertion-order, `next(iter(...))`, or "the first thing in the list" is silent corruption disguised as resilience.

## What this plan fixes

A walk through the bug chain, layer by layer. Each layer should have stopped the corruption. None did.

### Layer 1 — Frontend sends `model: null`

[`frontend/src/lib/components/SongDetailView.svelte:113-115`](../frontend/src/lib/components/SongDetailView.svelte#L113):
```svelte
$effect(() => {
    if (selectedModel === null && $activeModels.length > 0) {
        selectedModel = $activeModels[0].id;
    }
});
```

The Generate button is **enabled** even when `selectedModel === null`. The "happy path" relies on `activeModels` being populated, which depends on `available_models` having rows, which depends on a single alembic migration that ran once.

**Fix:** Generate button must be disabled when `selectedModel === null`. Tooltip explains why ("Select a model first" or "No models available — admin must enable one").

### Layer 2 — API accepts `model: null` (in three places)

[`api_models/songs.py:402-466`](../src/songmaker_cli/api_models/songs.py#L402-L466) declares **three** request models that take a model field, all with the same bug:

- `GenerateRequest` (line 402)
- `RepaintRequest` (line 417)
- `CoverRequest` (line 449)

All three already have a `_validate_model` field validator that rejects unknown strings — but each is gated on `if v is not None`, so `None` slips through. The field type is `model: str | None = None`. The API contract says model is optional. **This is the single most load-bearing wrong decision in the chain.** Once any of these endpoints accepts a `None`, every downstream layer has to pretend it knows what to do.

**Fix:** in all three models, drop the `| None = None`, drop the `if v is not None` guard in the existing validator. Diff is small:

```diff
- model: str | None = None
+ model: str

  @field_validator("model")
  @classmethod
- def _validate_model(cls, v: str | None) -> str | None:
-     if v is not None and v not in _VALID_MODEL_MODES:
+ def _validate_model(cls, v: str) -> str:
+     if v not in _VALID_MODEL_MODES:
          msg = f"model must be one of {sorted(_VALID_MODEL_MODES)}"
          raise ValueError(msg)
      return v
```

Pydantic returns 422 on missing or unknown model. No fallback path exists. **Fix all three models in the same commit** — fixing only `GenerateRequest` would leave repaint and cover as silent-fallback paths.

### Layer 3 — `resolve_model_mode(None)` falls through to dict order

[`src/songmaker_cli/config.py`](../src/songmaker_cli/config.py):
```python
def resolve_model_mode(model_name: str | None) -> str:
    if model_name:
        if model_name in _MODEL_NAME_TO_MODE:
            return _MODEL_NAME_TO_MODE[model_name]
        for mode in sorted(_BUILTIN_DEFAULTS, key=len, reverse=True):
            if mode in model_name:
                return mode
    return next(iter(_BUILTIN_DEFAULTS))   # ← bug
```

Three things wrong with the last line:
1. **Silent.** No log warning. The function doesn't tell anyone "hey I had to guess."
2. **Order-dependent.** `next(iter(_BUILTIN_DEFAULTS))` returns whichever key is FIRST in the dict literal. Today that's `'turbo'`. Reorder the dict for unrelated reasons → silent default changes → caller behavior changes silently. No test catches it because there's no test for `resolve_model_mode(None)` at all.
3. **Accepting `None` at all.** The signature should be `model_name: str` and the function should raise on unknown input.

**Fix:**
```python
def resolve_model_mode(model_name: str) -> str:
    """Map an ACE-Step model name to a builtin mode key.

    Raises:
        ValueError: if model_name doesn't match any known mode.
    """
    if model_name in _MODEL_NAME_TO_MODE:
        return _MODEL_NAME_TO_MODE[model_name]
    if model_name in _BUILTIN_DEFAULTS:
        return model_name
    raise ValueError(
        f"Unknown model: {model_name!r}. "
        f"Must be one of {sorted(_BUILTIN_DEFAULTS)} "
        f"or {sorted(_MODEL_NAME_TO_MODE)}"
    )
```

The substring fallback (`for mode in sorted(_BUILTIN_DEFAULTS, key=len, reverse=True): if mode in model_name`) also goes. It exists to map e.g. `'acestep-v15-some-future-variant'` → `'sft'` if `'sft'` happens to appear in the name. **That's a coincidence-based heuristic, not a contract.** A future model named e.g. `acestep-v17-xl-sft-distilled` would get matched as `xl-sft` purely by accident of naming. Better to fail explicitly and force a `_MODEL_NAME_TO_MODE` update when a new model appears.

**Call sites that pass `None` today** (must be updated when the signature tightens):

- [`config.py:187`](../src/songmaker_cli/config.py#L187) — `build_ace_config` passes `model_name` which can be None
- [`jobs.py:149`](../src/songmaker_cli/jobs.py#L149) — `_load_preset_params` passes `model_name` which can be None
- [`jobs.py:175`](../src/songmaker_cli/jobs.py#L175) — `_build_generation_context` passes `target_model` which can be None
- [`jobs.py:361`](../src/songmaker_cli/jobs.py#L361) — `_persist_generation_row` passes `ctx.model_name` (already resolved, but still typed as `| None`)

All four sites need their parameter types tightened to `str` and their callers verified. Don't trust this enumeration — re-grep `resolve_model_mode` before implementing.

### Layer 4 — DB column `generations.model_mode` is nullable

[`src/songmaker_cli/db/models.py`](../src/songmaker_cli/db/models.py):
```python
class Generation(...):
    ...
    model_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
```

The DB itself doesn't require a generation to have a model. **The last line of defense is gone.**

The column was added by [`e5f6a7b8c9d0_add_model_mode_to_generations.py:20`](../src/songmaker_cli/db/migrations/versions/e5f6a7b8c9d0_add_model_mode_to_generations.py#L20) as `nullable=True`. (The `nullable=False` `model_mode` in the baseline migration is on the unrelated `generation_presets` table — don't conflate them.)

**Verification before writing the migration:** run `\d generations` on the live DB to confirm the column is actually nullable (in case a later migration tightened it without updating the model). If it's already `NOT NULL`, only the SQLAlchemy model needs updating.

**Fix:** alembic migration that backfills NULLs to `'sft'` (the historic default), then adds the constraint:

```python
def upgrade():
    op.execute("UPDATE generations SET model_mode = 'sft' WHERE model_mode IS NULL")
    op.alter_column('generations', 'model_mode', nullable=False)
```

**Why `'sft'` and not a sentinel like `'unknown'`:** the corrupted-vs-correct distinction can't be perfectly recovered for the post-recovery rows (the original input is gone), and a sentinel makes downstream queries ugly with no real benefit. The migration's docstring should acknowledge the data loss.

### Layer 5 — `available_models` seed lives in alembic migration

The two seeding migrations:
- `b1c3f4a90210_add_available_models_table.py` — seeds `sft`, `turbo`
- `70d4935df72d_add_xl_model_variants.py` — seeds `xl-turbo`, `xl-sft`, `xl-base`

**Alembic seed migrations only run once.** TRUNCATE wipes them. There is no re-seed mechanism. The recovery script TRUNCATEd the table and bricked 3 features without anyone noticing because nothing checks at startup that the table is non-empty.

**Decision: split this into two pieces, ship the safe half now.**

The canonical list of *what modes exist* is moved to code in `constants.py`:

```python
# constants.py
AVAILABLE_MODEL_MODES: Final[frozenset[str]] = frozenset({
    'turbo', 'sft', 'xl-turbo', 'xl-sft', 'xl-base'
})
DEFAULT_MODEL_MODE: Final[str] = 'sft'
```

These constants are used by:
- `_VALID_MODEL_MODES` in `api_models/songs.py` (currently derived from `_BUILTIN_DEFAULTS.keys()`) — switch to import from `constants.py`
- The new `resolve_model_mode` raise message
- The migration backfill (`'sft'` → `DEFAULT_MODEL_MODE`)

**What this plan does NOT change** (deferred to a follow-up): the `available_models` *table* still exists, still tracks `is_active` per mode, and the admin UI still toggles it. Rewriting `list_active_models` / `list_all_models` to read from constants + DB join is the right next step but it's a behavioral change for admin UX and out of scope here. The startup health check ("refuse to serve if `available_models` is empty") is also deferred — once the constants exist and the API validates against them, the table being empty only breaks the admin model selector dropdown, not generation. That's a much smaller blast radius and can wait for the follow-up.

**What this buys us today:** the model-mode chain stops depending on `available_models` for *validation*. The table only controls *which subset is shown in the admin UI*. A future TRUNCATE can no longer corrupt generations.

### Layer 6 — No equivalent validation on generation submission

[`src/songmaker_cli/settings_api.py:api_create_preset`](../src/songmaker_cli/settings_api.py) checks `req.model_mode in active_ids` before saving a preset. But [`src/songmaker_cli/generation_api.py:api_generate_song`](../src/songmaker_cli/generation_api.py) **doesn't do the same check before enqueuing a generation**. A user with stale frontend state could send `model='xl-base'` to generate even after admin toggled xl-base off.

**Fix:** mirror the preset check in `api_generate_song`, `api_repaint_generation`, and `api_cover_generation`:
```python
active_ids = {m.id for m in list_active_models(session)}
if req.model not in active_ids:
    raise HTTPException(400, f"Model '{req.model}' is not currently available")
```

### Layer 7 — Worker-side label vs. truth (audited, no fix needed)

The most dangerous version of this bug isn't a wrong *label* — it's a row labeled `'sft'` whose audio was actually generated against `'turbo'`. This plan would not catch that. Audited the worker pool to confirm it doesn't happen:

- [`scheduler.py:129`](../src/songmaker_cli/scheduler.py#L129) `_pick_from(workers, target_mode)` filters online workers to those with `target_mode in w.loaded_modes`.
- [`scheduler.py:184`](../src/songmaker_cli/scheduler.py#L184) `_ensure_loaded` calls `/load_model` on the chosen worker if the mode isn't already loaded.
- [`acestep_worker/wrapper.py:185-192`](../src/acestep_worker/wrapper.py#L185-L192) `/generate` calls `cache.acquire_for_use(req.mode)` and **raises 409 if the mode isn't loaded**.

So the worker physically cannot generate against a mode it doesn't have loaded — the request gets rejected at `acquire_for_use`. Once `target_model` is non-None all the way through (this plan), the label and the truth match by construction.

**No code change in Layer 7.** Documented here so future readers don't have to re-derive it, and so the "no silent fallbacks" claim of this plan isn't quietly false.

## Other silent fallbacks worth fixing in the same pass

While we're auditing, these followed similar patterns and should get the same treatment:

| Location | Current | Should be |
|---|---|---|
| `config.py` `_BUILTIN_DEFAULTS["infer_method"] = "ode"` | Hardcoded default value baked into the dict | Fine — `ode` is a real choice with a documented reason. KEEP. (This is config, not validation.) |
| `acestep_engine/client.py` `use_random_seed` defaults to `True` if `seed` isn't `-1` | Implicit derived behavior | Already documented in CLAUDE.md known tech debt. Leave for now, but test it. |
| `claude/provider.py` Claude model resolution | Reads from env var with import-time defaults | Already documented in CLAUDE.md known tech debt. Leave for now. |
| Worker pool `scheduler.pick_worker` "no online workers → 503" | Already validates at boundary ✓ | Reference implementation of doing it right. |
| `api_helpers.check_song_access` / `check_album_access` | Already raises 403/404 ✓ | Reference for boundary validation. |

The ACE-Step worker pool work (Phases 1-8) is actually the **good** example here — it validates at boundaries (`check_generation_access`, `_has_online_acestep_worker`, etc.). The model-mode resolution is the regression.

## What this plan does NOT do

- **Doesn't change the worker pool architecture.** Phases 1-8 are stable. The audit in Layer 7 confirms it already validates correctly.
- **Doesn't rewrite `list_active_models` / `list_all_models`** to read from the new constants instead of the DB table. The table stays as the source of truth for `is_active` toggling. Constants are added alongside as an enforcement mechanism, not a replacement. Full Option-A migration is a follow-up.
- **Doesn't add a startup health check** for empty `available_models`. Once validation moves to constants, an empty table only breaks the admin UI dropdown — much smaller blast radius. Add the health check only if that becomes a recurring problem.
- **Doesn't backfill historical generations with the correct `model_mode`.** Rows corrupted at write time stay wrong; the original input is gone.
- **Doesn't add a generic "config validator" framework.** Just removes the specific silent fallbacks.
- **Only the principle half "reject at boundary" is used.** The other half ("named constant default + log when taken") is correct in general but not the right tool for the model-mode chain — there's no sensible default the system can pick on the user's behalf. Future plans applying this principle should consider both halves.

## Required tests (the gap that let this bug ship)

Currently `tests/` has **zero** tests for `resolve_model_mode`. The function has been silently returning whatever-the-first-dict-key-is for who knows how long. Required new tests:

### Backend (9 tests)

1. **`test_resolve_model_mode_known_modes`** — happy path: each of `'sft'`, `'turbo'`, `'xl-sft'`, `'xl-turbo'`, `'xl-base'` returns itself.
2. **`test_resolve_model_mode_full_name`** — `'acestep-v15-sft'` → `'sft'`, etc. for each entry in `_MODEL_NAME_TO_MODE`.
3. **`test_resolve_model_mode_unknown_raises`** — `'acestep-v999-quantum'` → raises ValueError with the list of valid modes in the message.
4. **`test_resolve_model_mode_none_raises`** — calling with `None` raises (TypeError from the type system, or explicit ValueError if we add a runtime guard). Documents that `None` is no longer a legal input.
5. **`test_generate_request_requires_model`** — `POST /api/songs/{id}/generate {count: 1}` (no model field) → 422. Repeat for `/repaint` and `/cover`.
6. **`test_generate_request_rejects_unknown_model`** — `{model: 'totally-fake'}` → 422. Repeat for `/repaint` and `/cover`.
7. **`test_generate_request_rejects_inactive_model`** — toggle `xl-sft` to inactive, send `{model: 'xl-sft'}` → 400. Repeat for `/repaint` and `/cover`.
8. **`test_available_models_seed_idempotency`** — start with the table empty, run the seed code, assert all 5 modes present, run it again, assert no duplicates.
9. **`test_generation_model_mode_not_null_after_migration`** — assert the column constraint is `NOT NULL` after the new alembic migration runs.

(Dropped the original "dict order independence" test — once `resolve_model_mode` raises on unknown input, dict order is irrelevant by construction. Test #3 covers the regression.)

### Frontend (3 tests)

1. **`SongDetailView.test.ts: generate button disabled when no model selected`** — render with `activeModels = []`, assert Generate button is disabled.
2. **`SongDetailView.test.ts: generate button enabled when model selected`** — render with `activeModels = [{id: 'sft', is_active: true}]`, assert button enabled.
3. **`SongDetailView.test.ts: shows admin warning when no models active`** — render with empty `activeModels`, assert a "No models enabled. Ask admin to enable one." message is visible.

**Total: 12 new tests (9 backend + 3 frontend).**

## Files Touched

| File | Change |
|---|---|
| `src/songmaker_cli/constants.py` | Add `AVAILABLE_MODEL_MODES: Final[frozenset[str]]` and `DEFAULT_MODEL_MODE: Final[str] = 'sft'` |
| `src/songmaker_cli/api_models/songs.py` | `GenerateRequest.model: str`, `RepaintRequest.model: str`, `CoverRequest.model: str` (drop `\| None = None` and the `if v is not None` guard in each `_validate_model`); switch `_VALID_MODEL_MODES` to import from `constants.py` |
| `src/songmaker_cli/config.py` | `resolve_model_mode(model_name: str)` — drop None branch, drop substring fallback, raise on unknown. Update `build_ace_config` `model_name` parameter type (line 178). |
| `src/songmaker_cli/generation_api.py` | Add `active_ids` check before enqueuing in `api_generate_song`, `api_repaint_generation`, `api_cover_generation` |
| `src/songmaker_cli/db/models.py` | `Generation.model_mode: Mapped[str]` (remove `\| None`, line 141) |
| `src/songmaker_cli/db/queries/generations.py` | `create_generation(... model_mode: str)` (line 44 — drop `\| None = None`) |
| `src/songmaker_cli/db/migrations/versions/<new>_model_mode_not_null.py` | NEW migration: backfill NULLs to `'sft'` + add NOT NULL constraint |
| `src/songmaker_cli/jobs.py` | `_build_generation_context.target_model: str` (line 166); `_load_preset_params.model_name: str` (line 139); update docstring at line 170 to remove the "If None, falls back" sentence; `_persist_generation_row` (line 361) — `ctx.model_name` is now `str`, no re-resolve needed |
| `src/songmaker_cli/music_worker.py` | `generate(... requested_model: str)` (line 45 — was `requested_model=None`) |
| `src/songmaker_cli/main.py` | Add `--model` parameter to `generate` CLI command (line 241); pass through to `/api/songs/{id}/generate` body. **Breaking change for CLI users.** Document in commit message. |
| `tests/test_config.py` (NEW or extend) | 4 `resolve_model_mode` tests |
| `tests/test_generation_api.py` | 3 sets of validation tests (Generate × 3 cases × 3 endpoints = 9 sub-tests, organized as 3 parametrized tests) |
| `tests/test_db.py` | 1 migration / NOT NULL test |
| `tests/test_settings_api.py` | 1 active_models seed idempotency test |
| `frontend/src/lib/components/SongDetailView.svelte` | Disable Generate button when `selectedModel === null`; add tooltip; add "no models enabled" warning |
| `frontend/src/lib/components/SongDetailView.test.ts` (NEW or extend) | 3 button-state tests |
| `CLAUDE.md` | (already done in same commit as this plan) Boundary validation principle |

**Not touched (per scope discipline):**
- Worker pool code
- Phase 8 image hierarchy
- Recovery scripts in `_recovery/`
- Any of the 8 other plans

## Implementation order with HARD checkpoints

1. **Add `AVAILABLE_MODEL_MODES` + `DEFAULT_MODEL_MODE` constants in `constants.py`** and switch `_VALID_MODEL_MODES` in `api_models/songs.py` to import from there. No behavior change yet — this is just the foundation steps 2-4 build on. **HARD checkpoint:** ruff + existing pytest still green.
2. **Update `resolve_model_mode` signature to `str` and raise on unknown.** Update all four call sites identified in Layer 3. Add the 4 unit tests. **HARD checkpoint:** `pytest tests/test_config.py -q` green.
3. **Make `model` required on all three request models** (`GenerateRequest`, `RepaintRequest`, `CoverRequest`). Update `music_worker.py` `generate(requested_model: str)`. Add the 3 parametrized API validation tests. **HARD checkpoint:** `pytest tests/test_generation_api.py -q` green + manually verify the API returns 422 on missing model for all three endpoints.
4. **Add the active-models check** to `api_generate_song`, `api_repaint_generation`, `api_cover_generation`. Add the inactive-model rejection test (parametrized over endpoints). **HARD checkpoint:** all tests pass.
5. **CLI: add `--model` to `songmaker generate`** in `main.py`. Pass through to the API. **HARD checkpoint:** `songmaker generate <song> --model sft` works against a running server; `songmaker generate <song>` (no `--model`) fails with a clear error.
6. **Frontend: disable Generate button when `selectedModel === null`** + warning UI. Add the 3 frontend tests. **HARD checkpoint:** `pnpm check && pnpm lint && pnpm test`.
7. **Verify DB column state.** Run `\d generations` on the live DB. If the column is already `NOT NULL`, skip step 8 and just update the SQLAlchemy model. Otherwise proceed.
8. **Alembic migration: backfill NULLs to `'sft'` + add `NOT NULL` constraint.** Add the migration test. **HARD checkpoint:** migration runs cleanly on a copy of the prod DB.
9. **`Generation.model_mode: Mapped[str]` + `create_generation(model_mode: str)`** in `db/models.py` and `db/queries/generations.py`. **HARD checkpoint:** ruff + pytest.
10. **Full suite + coverage.** `pytest tests/ -n auto -q --cov=...`. **HARD checkpoint:** 90%+ coverage, all green.
11. **Smoke test:** start the docker stack, hit the song view, verify the model dropdown works, verify Generate fails with 422 if you intercept the request and remove `model`, verify a real generation produces a row with the correct `model_mode`. Smoke test the CLI: `songmaker generate <song> --model sft`.
12. **Commit + push.**

## Out of scope (deferred to future plans)

- General audit of all silent fallbacks across the codebase. This plan only fixes the model-mode chain. The CLAUDE.md principle (added as part of this plan) is the long-term enforcement mechanism — future contributors and reviewers should catch new silent fallbacks during PR review.
- Migrating `available_models` to a pure code constant (Option A from Layer 5). Worth doing but requires admin UI updates. Can be a follow-up.
- Adding a generic config validator framework. Not needed for this fix.
- Backfilling the corrupted post-recovery generations to their actually-correct model_mode. Information is gone.

## Done criteria

- All 12 new tests pass (9 backend + 3 frontend)
- ruff + full pytest suite + pnpm check + pnpm lint + pnpm test all green
- Coverage stays at or above CI threshold
- Manually verified for **all three** endpoints (`/generate`, `/repaint`, `/cover`):
  - `{model: null}` or missing → 422
  - `{model: 'totally-fake'}` → 422
  - `{model: 'xl-sft'}` with `xl-sft` deactivated → 400
- Manually verified: a successful generation has the correct `model_mode` in the gen row, matching the requested model
- Manually verified: `songmaker generate <song> --model sft` works; `songmaker generate <song>` (no `--model`) fails clearly
- Migration runs cleanly on the live DB (or step skipped because column was already `NOT NULL`)
- The CLAUDE.md principle is in place

## What this plan IS

A targeted fix for one specific class of silent fallback (model mode resolution) plus the principle (added to CLAUDE.md) that prevents the next one. **Not** a sweeping refactor of every default in the codebase.

---

**Author:** Claude
**Date:** 2026-04-08
**Status:** Plan only. Awaiting user approval.
