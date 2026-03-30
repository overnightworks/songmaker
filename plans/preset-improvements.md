# Preset & Generation Settings Improvements

> **Status: DONE**

## Problem 1: Builtin defaults (SFT/TURBO) not available as preset chips on songs

When editing a song, the generation settings show user-created presets as chips but NOT the builtin SFT/TURBO defaults. Users can't quickly apply "use SFT defaults" from the song view — they have to go to global settings to see what the defaults are.

### Root Cause

`PresetChips.svelte` only reads from `$presets` store (user-created). Builtin defaults live in `$builtinDefaults` store and are only used as placeholders in `ParamControls`.

### Fix

- Show builtin modes (SFT, TURBO) as chips in `PresetChips.svelte` before user presets
- Clicking a builtin chip applies all its values (full parameter set, not just overrides)
- Style them differently from user presets (e.g., no border, just the mode tag)
- Pass `$builtinDefaults` into `PresetChips` as a new prop

### Files to Touch

| File | Change |
|------|--------|
| `PresetChips.svelte` | Accept `builtins` prop, render builtin chips before user presets |
| `GenerationSettings.svelte` | Pass `$builtinDefaults` to `PresetChips` |

---

## Problem 2: Presets only apply overrides, not full parameter sets

When a user creates a preset and only changes `inference_steps`, clicking that preset chip on a song only sets `inference_steps`. All other params stay undefined (showing placeholders). Expected behavior: clicking a preset should apply ALL parameters for a complete, predictable config.

### Root Cause

Presets store only the keys the user explicitly changed (sparse dict). When loaded via `onload({ ...preset.params })`, only those keys are set in `$editGenParams`. The UI shows placeholders for missing keys, which is correct for "override mode" but confusing for "apply this preset."

### Fix

- When saving a preset, merge the current placeholders (builtin + global defaults) with user overrides to create a complete parameter set
- Store the full merged params, not just the overrides
- This way clicking a preset always produces a complete, deterministic config

### Files to Touch

| File | Change |
|------|--------|
| `settings/generation/+page.svelte` | Merge builtins + global defaults into preset params before saving |

---

## Problem 3: Cannot edit existing presets

The settings page shows presets with `set default` and `delete` buttons but no `edit` button. The backend already supports `PUT /api/settings/presets/{id}` with partial updates.

### Fix

- Add an `edit` button to each preset row in the settings page
- Clicking it opens the same form as "New Preset" but pre-filled with the preset's current values
- Save calls `updatePreset()` instead of `savePreset()`

### Files to Touch

| File | Change |
|------|--------|
| `settings/generation/+page.svelte` | Add edit button, pre-fill form, call `updatePreset` on save |
| `stores/presets.ts` | Add `updatePreset` action wrapping the API call |

---

## Problem 4: Cannot unset default preset

Once a preset is marked as default, the only option is to switch the default to another preset. There's no way to clear the default entirely. The backend supports `PUT /api/settings/presets/{id}` with `is_default: false`.

### Fix

- When a preset is already default, show "unset default" button instead of "set default"
- Calls `updatePreset(id, { is_default: false })` via the store

### Files to Touch

| File | Change |
|------|--------|
| `settings/generation/+page.svelte` | Toggle button text/action based on `is_default` |
| `stores/presets.ts` | Add `unsetDefault` action or extend `setDefault` to toggle |

---

## Priority

Problem 1 (builtins as chips) → Problem 2 (full preset values) → Problem 4 (unset default) → Problem 3 (edit presets)

## Constraints

- Backend already supports all needed operations — changes are frontend-only
- `ParamControls` placeholder behavior must stay the same (shows builtin/global defaults for unset keys)
- Builtin defaults come from `GET /api/settings/generation-builtins` and are mode-keyed (`{ sft: {...}, turbo: {...} }`)
- Preset `model_mode` must match the active model for generation to use the right base config
