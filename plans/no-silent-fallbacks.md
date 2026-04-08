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

### Layer 2 — API accepts `model: null`

[`src/songmaker_cli/api_models/songs.py`](../src/songmaker_cli/api_models/songs.py):
```python
class GenerateRequest(BaseModel):
    count: int = Field(1, ge=1, le=10)
    model: str | None = None     # ← optional
    version_id: str | None = None
    seed: int | None = Field(None, ge=-1)
```

The API contract says model is optional. **This is the single most load-bearing wrong decision in the chain.** Once the API accepts a `None`, every downstream layer has to pretend it knows what to do.

**Fix:** make `model` required:
```python
class GenerateRequest(BaseModel):
    count: int = Field(1, ge=1, le=10)
    model: str    # required
    version_id: str | None = None
    seed: int | None = Field(None, ge=-1)

    @field_validator("model")
    @classmethod
    def _validate_model(cls, v: str) -> str:
        if v not in _VALID_MODEL_MODES:
            raise ValueError(f"model must be one of {sorted(_VALID_MODEL_MODES)}")
        return v
```

Pydantic returns 422 on missing or unknown model. No fallback path exists.

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

The substring fallback (`for mode in sorted(_BUILTIN_DEFAULTS, key=len, reverse=True): if mode in model_name`) also goes. It exists to map e.g. `'acestep-v15-some-future-variant'` → `'sft'` if `'sft'` happens to appear in the name. **That's a coincidence-based heuristic, not a contract.** If a future model is named `acestep-v16-soft` (with substring `'sft'`), the substring search would silently miscategorize it. Better to fail explicitly and force a `_MODEL_NAME_TO_MODE` update when a new model appears.

### Layer 4 — DB column `generations.model_mode` is nullable

[`src/songmaker_cli/db/models.py`](../src/songmaker_cli/db/models.py):
```python
class Generation(...):
    ...
    model_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
```

The DB itself doesn't require a generation to have a model. **The last line of defense is gone.**

**Fix:** alembic migration to set `model_mode` to `NOT NULL`. Backfill any existing NULLs to `'sft'` (or whatever the current default should be) before the constraint.

```python
def upgrade():
    op.execute("UPDATE generations SET model_mode = 'sft' WHERE model_mode IS NULL")
    op.alter_column('generations', 'model_mode', nullable=False)
```

### Layer 5 — `available_models` seed lives in alembic migration

The two seeding migrations:
- `b1c3f4a90210_add_available_models_table.py` — seeds `sft`, `turbo`
- `70d4935df72d_add_xl_model_variants.py` — seeds `xl-turbo`, `xl-sft`, `xl-base`

**Alembic seed migrations only run once.** TRUNCATE wipes them. There is no re-seed mechanism. The recovery script TRUNCATEd the table and bricked 3 features without anyone noticing because nothing checks at startup that the table is non-empty.

**Two viable fixes:**

**Option A — Move the canonical list to code:**
```python
# constants.py
AVAILABLE_MODEL_MODES: Final[frozenset[str]] = frozenset({
    'turbo', 'sft', 'xl-turbo', 'xl-sft', 'xl-base'
})
DEFAULT_ACTIVE_MODEL_MODES: Final[frozenset[str]] = frozenset({'sft'})
```

The `available_models` table becomes admin-controlled state for *which* of the canonical modes are user-visible. The list of *what modes exist* lives in code where it can't be wiped. The `is_active` flag is the only thing the table tracks.

**Option B — Startup health check:**
On app startup, check `SELECT COUNT(*) FROM available_models`. If 0, log a critical error and refuse to serve traffic until the admin runs a re-seed CLI command (`uv run songmaker reseed-models`).

**Recommendation: A.** Code constants are tested, version-controlled, and impossible to wipe. Option B is a band-aid on the underlying "data masquerading as schema" problem.

### Layer 6 — No equivalent validation on generation submission

[`src/songmaker_cli/settings_api.py:api_create_preset`](../src/songmaker_cli/settings_api.py) checks `req.model_mode in active_ids` before saving a preset. But [`src/songmaker_cli/generation_api.py:api_generate_song`](../src/songmaker_cli/generation_api.py) **doesn't do the same check before enqueuing a generation**. A user with stale frontend state could send `model='xl-base'` to generate even after admin toggled xl-base off.

**Fix:** mirror the preset check in the generation endpoint:
```python
active_ids = {m.id for m in list_active_models(session)}
if req.model not in active_ids:
    raise HTTPException(400, f"Model '{req.model}' is not currently available")
```

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

- **Doesn't change the worker pool architecture.** Phases 1-8 are stable. Don't touch.
- **Doesn't migrate `available_models` to code immediately.** That's Option A and is the correct fix, but it's a behavioral change for the admin UI (the toggle would persist as `is_active` only). Sub-decision deferred to implementation.
- **Doesn't backfill historical generations with corrected `model_mode`.** Existing rows that say `'turbo'` when the user generated against `'sft'` stay wrong. They were corrupted at write time and we can't recover the truth. Mention this in the rollout note.
- **Doesn't add a generic "config validator" framework.** Just removes the specific silent fallbacks.

## Required tests (the gap that let this bug ship)

Currently `tests/` has **zero** tests for `resolve_model_mode`. The function has been silently returning whatever-the-first-dict-key-is for who knows how long. Required new tests:

### Backend

1. **`test_resolve_model_mode_known_modes`** — happy path: each of `'sft'`, `'turbo'`, `'xl-sft'`, `'xl-turbo'`, `'xl-base'` returns itself.
2. **`test_resolve_model_mode_full_name`** — `'acestep-v15-sft'` → `'sft'`, etc.
3. **`test_resolve_model_mode_unknown_raises`** — `'acestep-v999-quantum'` → raises ValueError.
4. **`test_resolve_model_mode_none_raises`** — calling with `None` (after type check is removed) raises TypeError or ValueError. Documents that `None` is no longer a legal input.
5. **`test_generate_request_requires_model`** — `POST /api/songs/{id}/generate {count: 1}` (no model field) → 422.
6. **`test_generate_request_rejects_unknown_model`** — `POST .../generate {model: 'totally-fake'}` → 422.
7. **`test_generate_request_rejects_inactive_model`** — toggle `xl-sft` to inactive, send `{model: 'xl-sft'}` → 400 "Model 'xl-sft' is not currently available".
8. **`test_available_models_seed_idempotency`** — start with the table empty, run the seed code, assert all 5 modes present, run it again, assert no duplicates.
9. **`test_generation_model_mode_not_null_after_migration`** — assert the column constraint is `NOT NULL` after the new alembic migration.
10. **`test_resolve_model_mode_dict_order_independence`** — dependency-injection test where you pass a reordered `_BUILTIN_DEFAULTS` and assert the resolution result is unchanged. (Catches the next person who reorders the dict.)

### Frontend

1. **`SongDetailView.test.ts: generate button disabled when no model selected`** — render with `activeModels = []`, assert Generate button is disabled, assert clicking it does nothing.
2. **`SongDetailView.test.ts: generate button enabled when model selected`** — render with `activeModels = [{id: 'sft', is_active: true}]`, assert button enabled.
3. **`SongDetailView.test.ts: shows admin warning when no models active`** — render with empty activeModels, assert a "No models enabled. Ask admin to enable one." message is visible.

## Files Touched

| File | Change |
|---|---|
| `src/songmaker_cli/api_models/songs.py` | `GenerateRequest.model: str` (remove `None`); `RegenerateRequest.model: str` if it has the same field |
| `src/songmaker_cli/config.py` | `resolve_model_mode(model_name: str)` — drop None branch, drop substring fallback, raise on unknown |
| `src/songmaker_cli/generation_api.py` | Add `active_ids` check before enqueuing generation |
| `src/songmaker_cli/db/models.py` | `Generation.model_mode: Mapped[str]` (remove `\| None`) |
| `src/songmaker_cli/db/migrations/versions/<new>_model_mode_not_null.py` | NEW alembic migration: backfill NULLs + add NOT NULL constraint |
| `src/songmaker_cli/constants.py` | Add `AVAILABLE_MODEL_MODES`, `DEFAULT_ACTIVE_MODEL_MODES`, `DEFAULT_MODEL_MODE` constants (Option A) |
| `src/songmaker_cli/db/queries/settings.py` | If Option A: rewrite `list_active_models` / `list_all_models` to read from constants + DB join, not raw DB |
| `src/songmaker_cli/jobs.py` | `_build_generation_context` — `target_model: str` (no None), no `resolve_model_mode(None)` path |
| `src/songmaker_cli/music_worker.py` | `generate(... requested_model: str)` (was `requested_model=None`) |
| `tests/test_config.py` (NEW or extend) | 5 `resolve_model_mode` tests |
| `tests/test_generation_api.py` | 3 `GenerateRequest` validation tests |
| `tests/test_db.py` | 1 migration / NOT NULL test |
| `tests/test_settings_api.py` | 1 active_models seed idempotency test |
| `frontend/src/lib/components/SongDetailView.svelte` | Disable Generate button when `selectedModel === null`; add tooltip; add "no models" warning |
| `frontend/src/lib/components/SongDetailView.test.ts` (NEW or extend) | 3 button-state tests |
| `CLAUDE.md` | (already done in same commit as this plan) Add the boundary validation principle |
| `docs/architecture.md` (optional) | Note the boundary-validation principle in the high-level overview |

**Not touched (per scope discipline):**
- Worker pool code
- Phase 8 image hierarchy
- Recovery scripts in `_recovery/`
- Any of the 8 other plans

## Implementation order with HARD checkpoints

1. **Add `AVAILABLE_MODEL_MODES` + `DEFAULT_MODEL_MODE` constants in `constants.py`**, no behavior change yet.
2. **Update `resolve_model_mode` to drop the None branch.** Add the 5 unit tests. **HARD checkpoint:** all tests pass.
3. **Make `GenerateRequest.model` required.** Add the 3 API validation tests. **HARD checkpoint:** all tests pass + manually verify the API returns 422 on missing model.
4. **Add the active-models check to `api_generate_song`.** Add the test. **HARD checkpoint:** all tests pass.
5. **Frontend: disable Generate button when `selectedModel === null`** + add the warning UI. Add the 3 frontend tests. **HARD checkpoint:** `pnpm check && pnpm lint && pnpm test`.
6. **Alembic migration: backfill NULLs + add `NOT NULL` constraint.** **HARD checkpoint:** migration runs cleanly on a copy of the prod DB.
7. **`Generation.model_mode: Mapped[str]`** in `models.py`. **HARD checkpoint:** ruff + pytest.
8. **Smoke test:** start the docker stack, hit the song view, verify the model dropdown works, verify Generate fails with 422 if you intercept the request and remove `model`, verify a real generation produces a row with the correct `model_mode`.
9. **Commit + push.**

## Migration concern — historical generations with wrong model_mode

After the recovery, some existing generations have `model_mode='turbo'` even though they were generated against sft (or before the recovery, against whatever was actually loaded). **We can't recover the truth** — those rows are corrupted at write time and the original input is gone.

**Two options for the migration:**
- **A.** Backfill all NULL `model_mode` to a sentinel like `'unknown'`. Add `'unknown'` to the allowed values. Document that any row with `'unknown'` is from before the constraint.
- **B.** Backfill all NULL to `'sft'` (the most common default). Lose information but keep the schema clean.
- **C.** Backfill NULL to `'sft'` and ALSO backfill any row where `model_mode='turbo'` AND `created_at < <recovery_timestamp>` to `'unknown'`. Catches the recovery-corrupted rows.

**Recommendation: B.** The corrupted-vs-correct distinction can't be perfectly recovered, and a sentinel value makes downstream queries ugly. Acknowledge the data loss in the migration's docstring.

## Estimated effort

- Backend changes + tests: ~2 hours
- Frontend changes + tests: ~1 hour
- Migration + manual verification: ~30 min
- Smoke test loop: ~30 min
- **Total: ~4 hours**

## Out of scope (deferred to future plans)

- General audit of all silent fallbacks across the codebase. This plan only fixes the model-mode chain. The CLAUDE.md principle (added as part of this plan) is the long-term enforcement mechanism — future contributors and reviewers should catch new silent fallbacks during PR review.
- Migrating `available_models` to a pure code constant (Option A from Layer 5). Worth doing but requires admin UI updates. Can be a follow-up.
- Adding a generic config validator framework. Not needed for this fix.
- Backfilling the corrupted post-recovery generations to their actually-correct model_mode. Information is gone.

## Done criteria

- All 11 new tests pass (10 backend + 3 frontend)
- ruff + pytest + pnpm check + pnpm lint + pnpm test all green
- Manually verified: hitting the API with `{model: null}` returns 422
- Manually verified: hitting the API with `{model: 'totally-fake'}` returns 422
- Manually verified: hitting the API with a deactivated model returns 400
- Manually verified: a successful generation has the correct `model_mode` in the gen row
- Migration runs cleanly on the live DB
- The CLAUDE.md principle is in place

## What this plan IS

A targeted fix for one specific class of silent fallback (model mode resolution) plus the principle (added to CLAUDE.md) that prevents the next one. **Not** a sweeping refactor of every default in the codebase.

---

**Author:** Claude
**Date:** 2026-04-08
**Status:** Plan only. Awaiting user approval.
