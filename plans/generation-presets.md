# Generation Presets

**Status**: Done

## Problem

Generation settings live in three places with no single source of truth:

1. **AceStepConfig defaults** — hardcoded in `acestep_engine/models.py` (the ultimate fallback)
2. **Model-specific overrides** — hardcoded in `config.py` (`_SFT_DEFAULTS`, `_TURBO_DEFAULTS`) and duplicated in `GenerationSettings.svelte` (`BUILTIN_DEFAULTS`)
3. **Global user defaults** — a single JSON file at `_output/generation_defaults.json`, one dict per model mode

The frontend has its own copy of the builtin defaults. If someone changes `config.py`, the frontend shows stale values. There's also no way to save multiple configs — e.g. "my metal settings" vs "my lo-fi settings" — and pick one as the go-to default.

## Goal

- **Single source of truth** for builtin defaults: backend serves them, frontend reads them
- **Named presets**: users save parameter sets with a name, reuse across songs
- **Active default**: one preset per model mode is marked as the default — used when generating any song that doesn't have its own overrides
- **Preserve existing merge chain**: CLI overrides > song version params > active preset > builtin defaults

## Non-Goals

- Per-song preset assignment (version `generation_params` already does this)
- Sharing presets between users (single-user tool today; easy to add user_id FK later)
- Preset inheritance or composition
- Preset versioning / history

## Design

### Data Model

New table `generation_preset`:

```
generation_preset
├── id: UUID (PK)
├── name: str (unique per user+model_mode)
├── model_mode: str ("turbo" | "sft")
├── params: JSON (same shape as GenerationParams)
├── is_default: bool (default False)
├── created_by: UUID (FK → user.id)
├── created_at: datetime
├── updated_at: datetime
```

**Constraint**: At most one preset with `is_default=True` per `(created_by, model_mode)`. Enforced in application code (not DB constraint — SQLite partial unique indexes are fragile).

### Builtin Defaults Endpoint

```
GET /api/settings/generation-builtins
→ { "turbo": { inference_steps: 8, ... }, "sft": { inference_steps: 50, ... } }
```

Returns the hardcoded model defaults from `config.py`. No auth required (read-only, not sensitive). This is the single source of truth the frontend reads instead of maintaining its own `BUILTIN_DEFAULTS`.

### Presets CRUD

```
GET    /api/settings/presets                    → PresetItem[]
POST   /api/settings/presets                    → PresetItem
PUT    /api/settings/presets/{id}               → PresetItem
DELETE /api/settings/presets/{id}               → 204
POST   /api/settings/presets/{id}/set-default   → PresetItem
```

- **List**: returns all presets for the current user, ordered by model_mode then name
- **Create**: name + model_mode + params. If `is_default` is true, clears any existing default for that model_mode first.
- **Update**: name and/or params. Cannot change model_mode (delete + create instead).
- **Delete**: if deleting the active default, no default is set (falls back to builtins).
- **Set-default**: marks this preset as default for its model_mode, clears previous default.

### API Models

```python
class PresetCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    model_mode: str  # validated: "turbo" | "sft"
    params: GenerationParams
    is_default: bool = False

class PresetUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    params: GenerationParams | None = None
    is_default: bool | None = None

class PresetResponse(BaseModel):
    id: str
    name: str
    model_mode: str
    params: dict
    is_default: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_orm(cls, preset): ...
```

### Config Merge Chain (Updated)

Current: `AceStepConfig defaults → _MODEL_DEFAULTS → global JSON defaults → version params → CLI overrides`

New: `AceStepConfig defaults → builtin model defaults → active preset params → version params → CLI overrides`

The global JSON file (`generation_defaults.json`) is replaced by the active preset. Migration: on first startup after upgrade, if the JSON file exists, import its contents as a preset named "Imported defaults" and mark it as default, then delete the file.

### Frontend Changes

#### Remove `BUILTIN_DEFAULTS` from `GenerationSettings.svelte`

Replace with a `fetchBuiltinDefaults()` call on mount. Cache in a store or module-level variable (builtins don't change at runtime).

#### Preset Management UI

Add to the generation settings panel:

- **Preset selector**: dropdown showing saved presets for the current model mode + "Builtins" option
- **Save as preset**: button that saves current settings as a new named preset
- **Set as default**: star/toggle on preset list to mark active default
- **Delete preset**: with confirmation
- **Visual indicator**: show which values differ from builtins (existing `hasOverrides` logic)

#### Preset Store (`stores/presets.ts`)

```typescript
export const presets = writable<PresetItem[]>([]);
export const builtinDefaults = writable<Record<string, VersionGenerationParams>>({});

export async function loadPresets(): Promise<void> { ... }
export async function loadBuiltins(): Promise<void> { ... }
export async function savePreset(name: string, mode: string, params: VersionGenerationParams): Promise<void> { ... }
export async function setDefault(presetId: string): Promise<void> { ... }
export async function deletePreset(presetId: string): Promise<void> { ... }
```

### DB Queries

New file: `db/queries/settings.py`

```python
def list_presets(session, user_id) -> list[GenerationPreset]
def get_preset(session, preset_id, user_id) -> GenerationPreset | None
def create_preset(session, ...) -> GenerationPreset
def update_preset(session, preset_id, ...) -> GenerationPreset
def delete_preset(session, preset_id, user_id) -> None
def get_default_preset(session, user_id, model_mode) -> GenerationPreset | None
def set_default_preset(session, preset_id, user_id) -> None  # clears old, sets new
def clear_default_preset(session, user_id, model_mode) -> None
```

### Migration

Alembic migration adds `generation_preset` table. A data migration step checks for `_output/generation_defaults.json` — if found, creates presets from its contents and removes the file.

### CLI

No CLI changes needed. The CLI already uses `build_ace_config()` which will read the active preset from DB instead of the JSON file. CLI-specific overrides (flags) still win.

## Files Changed

| File | Change |
|------|--------|
| `db/models.py` | Add `GenerationPreset` model |
| `db/queries/settings.py` | New: preset CRUD queries |
| `db/queries/__init__.py` | Re-export settings queries |
| `api_models.py` | Add `PresetCreateRequest`, `PresetUpdateRequest`, `PresetResponse` |
| `settings_api.py` | New: presets CRUD + builtins endpoint (replaces gen-defaults in `chat_api.py`) |
| `api.py` | Include settings router |
| `chat_api.py` | Remove generation defaults endpoints |
| `config.py` | `load_generation_defaults()` → reads active preset from DB; remove JSON file I/O; expose `get_builtin_defaults()` |
| `jobs.py` | Pass active preset into `build_ace_config()` |
| Alembic migration | New table + data migration |
| `frontend/src/lib/api/types.ts` | Add `PresetItem` type |
| `frontend/src/lib/api/client.ts` | Add preset API functions, `fetchBuiltinDefaults()` |
| `frontend/src/lib/stores/presets.ts` | New: preset state management |
| `frontend/src/lib/components/GenerationSettings.svelte` | Remove `BUILTIN_DEFAULTS`, add preset selector/management |
| Tests | New: `test_settings_api.py`, update `test_config.py`, frontend preset store tests |

## Risks

- **Migration of existing JSON defaults**: if the JSON file has values, they must be preserved. The data migration handles this.
- **config.py currently doesn't take a DB session**: `build_ace_config()` is called from `jobs.py` which already has a session. Pass the active preset's params dict directly instead of making config.py DB-aware.
- **Admin vs user presets**: currently generation-defaults are admin-only. Presets should be per-user (any role). Builtins endpoint can be public (or at least any authenticated user).

## Priority

Medium — fixes the dual-source-of-truth issue flagged in the architecture review, and adds a commonly requested workflow improvement. No urgent deadline.
