# User Presets & Default Generation Config

> **Status: DONE** — Phases 1-5 implemented. Phase 6 (auto-apply on song creation) deferred — songs inherit at generation time, explicit apply on creation is optional.

## Summary

Users can create their own generation presets, pick a default config (Inherit / SFT / TURBO / any preset), and new songs automatically get that default applied. Song generation settings show all options grouped: Inherit → Builtins → User presets → Admin presets.

---

## Phase 1: User-facing preset CRUD (backend)

Currently preset endpoints require admin. Users need their own presets scoped by `created_by`.

### Changes

| File | Change |
|------|--------|
| `settings_api.py` | Add user-facing preset endpoints: `GET/POST/PUT/DELETE /api/settings/my-presets` scoped to `user.id`. Keep admin endpoints for global presets |
| `db/queries/settings.py` | Add `list_user_presets(session, user_id)`, `create_user_preset(...)`, `update_user_preset(...)`, `delete_user_preset(...)` with ownership checks |
| `db/queries/__init__.py` | Re-export new query functions |
| `api_models/settings.py` | Reuse existing `PresetCreateRequest` / `PresetUpdateRequest` / `PresetResponse` |
| Tests | CRUD tests for user presets, ownership isolation (user A can't see user B's presets) |

### Notes

- Admin presets have `created_by=NULL` — shared, visible to everyone
- User presets have `created_by=user_id` — private to that user
- No schema change needed — `GenerationPreset.created_by` already exists and is nullable

---

## Phase 2: User default generation config (backend)

New user setting: "what config to apply when I create a song or generate without explicit overrides."

### Options for default_generation_config

- `"inherit"` — use admin global defaults (resolved at generation time)
- `"sft"` — builtin SFT params (full snapshot)
- `"turbo"` — builtin TURBO params (full snapshot)
- `{preset_id}` — a specific preset (user or admin), stored as UUID

### Changes

| File | Change |
|------|--------|
| `db/models.py` | Add `default_generation_config` column to `User` model: `String(36), nullable=True, default=None`. `None` = inherit |
| `db/migrations/versions/` | Alembic migration adding the column |
| `api_models/settings.py` | Add `DefaultConfigRequest(config: str \| None)` and `DefaultConfigResponse(config: str \| None)` |
| `settings_api.py` | Add `GET/PUT /api/settings/default-config` — reads/writes the user's default |
| `db/queries/settings.py` | Add `get_user_default_config(session, user_id)`, `set_user_default_config(session, user_id, config)` |
| `jobs.py` | In `_load_preset_params()`, resolve the user's `default_generation_config` — if it's a preset ID, load that preset; if "sft"/"turbo", load builtins; if null, fall through to global defaults |
| Tests | Default config CRUD, resolution at generation time for each option |

### Resolution at generation time

```
1. Song has explicit generation_params? → use them (existing behavior)
2. User has default_generation_config?
   - "sft" / "turbo" → load builtin defaults for that mode
   - preset UUID → load that preset's params
   - null / "inherit" → fall through
3. Admin global defaults → applied
4. Builtin model defaults → base fallback
```

This preserves the existing layer chain. Step 2 is the new insertion point.

---

## Phase 3: Frontend — user preset management

### Changes

| File | Change |
|------|--------|
| `stores/presets.ts` | Split into `userPresets` and `adminPresets` stores. Add CRUD actions for user presets using `/api/settings/my-presets` |
| `api/client.ts` | Add `fetchMyPresets()`, `createMyPreset()`, `updateMyPreset()`, `deleteMyPreset()`, `fetchDefaultConfig()`, `updateDefaultConfig()` |
| `settings/generation/+page.svelte` | Show user's own presets with create/edit/delete. Show admin presets read-only below. Remove admin gate on preset creation |

---

## Phase 4: Frontend — default config selector

### Changes

| File | Change |
|------|--------|
| `settings/generation/+page.svelte` | Add "Default for new songs" section at top. Radio/chip selector: Inherit (default) · SFT · TURBO · [user presets] · [admin presets]. Calls `PUT /api/settings/default-config` on change |
| `stores/presets.ts` | Add `defaultConfig` writable store, `loadDefaultConfig()`, `saveDefaultConfig()` |

### UI layout

```
DEFAULT FOR NEW SONGS
[Inherit] [SFT] [TURBO] [My Preset 1] [My Preset 2] [Admin Preset 1]
                                        ↑ currently selected (highlighted)

MY PRESETS
  Preset 1    sft    [edit] [delete]
  Preset 2    turbo  [edit] [delete]
  [New Preset]

ADMIN PRESETS (read-only)
  Shared Preset 1    sft    default
  Shared Preset 2    turbo
```

---

## Phase 5: Frontend — song generation settings

### Changes

| File | Change |
|------|--------|
| `PresetChips.svelte` | Show grouped chips: Inherit → SFT → TURBO → User presets → Admin presets. Current selection highlighted. Inherit = reset to null |
| `GenerationSettings.svelte` | Pass both user and admin presets + builtins to `PresetChips` |

### Chip behavior on a song

- **Inherit** → sets `generation_params = null`, shows "using defaults" state
- **SFT / TURBO** → sets full builtin params explicitly on song
- **Any preset** → sets full preset params explicitly on song
- **Reset to defaults** button removed (Inherit chip replaces it)

---

## Phase 6: Auto-apply default on song creation

### Changes

| File | Change |
|------|--------|
| `song_api.py` | In `api_create_song()`, if `req.generation_params` is None, resolve user's `default_generation_config` and apply. Only for "sft"/"turbo"/preset — "inherit" stays null |

### Behavior

- User default = "inherit" → song created with `generation_params = null` (existing behavior)
- User default = "sft" → song created with full SFT params stored
- User default = preset → song created with full preset params stored
- User explicitly passes params in request → those take precedence (existing behavior)

---

## Priority

Phase 1 → Phase 2 → Phase 3+4 (parallel) → Phase 5 → Phase 6

## Constraints

- No breaking changes to existing API — admin preset endpoints stay as-is
- `created_by=NULL` means admin/shared preset, `created_by=user_id` means private
- Preset `model_mode` is informational — doesn't restrict which model runs the generation
- Generation resolution chain (jobs.py `build_ace_config`) must stay backward-compatible
- Frontend type generation (`generate_types.py`) must run after API model changes
