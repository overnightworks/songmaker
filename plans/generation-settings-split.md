# GenerationSettings.svelte Component Split

## Problem

908-line component with four interleaved responsibilities: parameter controls, preset CRUD, global defaults editing, and orchestration. The param grid is duplicated verbatim (once for per-song overrides, once for defaults editor).

## Target Architecture

```
GenerationSettings.svelte  (~80 lines, thin shell)
  ├── PresetManager.svelte  (~120 lines)
  ├── ParamControls.svelte  (~130 lines, used twice)
  └── DefaultsEditor.svelte (~150 lines, contains ParamControls)
```

## Component Interfaces

### ParamControls.svelte

```typescript
interface Props {
  values: VersionGenerationParams;
  placeholders: Required<VersionGenerationParams>;
  onchange: (params: VersionGenerationParams) => void;
}
```

Generic settings grid with 11 fields. Receives values + placeholders, emits full updated params on change. Used by both the main view and DefaultsEditor.

### PresetManager.svelte

```typescript
interface Props {
  hasOverrides: boolean;
  currentParams: VersionGenerationParams;
  onload: (params: VersionGenerationParams) => void;
}
```

Preset chips, save form, management panel. Reads `$presets` store directly.

### DefaultsEditor.svelte

```typescript
interface Props {
  visible: boolean;
  globalDefaults: Record<string, VersionGenerationParams>;
  builtins: Record<string, Required<VersionGenerationParams>>;
  onclose: () => void;
  onsave: (updated: Record<string, VersionGenerationParams>) => void;
}
```

Model tabs (turbo/sft), edit + save. Uses ParamControls internally.

### GenerationSettings.svelte (shell)

Keeps: `open`, `showDefaults`, `globalDefaults` state. Computes `FALLBACK_DEFAULTS`, `builtins`, `effectiveDefaults`. Composes the three subcomponents.

## Key Decisions

- **No two-way bindings cross boundaries** — all communication via props + callbacks.
- **Styles duplicated per component** — no shared CSS file (no precedent in codebase). Minor duplication (~20 lines for `.settings-grid`/`.setting`).
- **`globalDefaults` lives in shell** — passed down to DefaultsEditor, used to compute effectiveDefaults for ParamControls.

## Steps

1. Create `ParamControls.svelte` — extract settings grid
2. Create `PresetManager.svelte` — extract preset CRUD UI
3. Create `DefaultsEditor.svelte` — extract global defaults panel (uses ParamControls)
4. Rewrite `GenerationSettings.svelte` as thin shell
5. Run `cd frontend && pnpm check && pnpm lint && pnpm test`
