# Generation-Centric Editing Mode

## Problem

Repaint and cover currently use a modal dialog that's disconnected from the song editor. The user can't:
- See which version a generation was built from
- Switch to a different version for the repaint/cover (e.g. repaint gen#24's audio using version 3's lyrics)
- Adjust generation settings in the same context as lyrics/prompt editing
- Use the full GenerationSettings panel (presets, all params) — only a limited subset

The modal duplicates controls that already exist in the editor (lyrics, prompt) and can't access controls it needs (generation settings, version selector).

## Design

When the user selects a generation and initiates repaint or cover, the editor tab becomes the editing context for that operation — not a separate modal.

### Core Concept

**Repaint/cover is just a generation with extra inputs** (time range + source audio). The editor already handles lyrics, prompt, version selection, and generation settings. Repaint adds a time range picker; cover adds a strength slider. Everything else is reused.

### Workflow

1. User selects a generation in the generations list
2. User clicks "Repaint" (or "Cover") on that generation
3. The editor tab switches to **repaint mode**:
   - Shows which version this generation was created from (default selection)
   - Version selector is active — user can pick a different version
   - Lyrics and prompt fields show the selected version's content (editable)
   - GenerationSettings panel shows the selected version's params (editable)
   - A **time range picker** appears at the top of the editor (repaint only)
   - A **cover strength slider** appears (cover only)
   - The "Generate" button changes to "Repaint" / "Cover"
4. User adjusts anything they want — version, lyrics, prompt, settings, time range
5. User hits "Repaint" — sends the request with all current editor state
6. New generation appears in the list, attributed to the selected version
7. Editor exits repaint mode (returns to normal editing)

### What Changes

**Frontend:**

| Component | Change |
|-----------|--------|
| `SongDetailView` | Manages repaint/cover mode state instead of modal dialog |
| `SongEditor` | Accepts a `mode` prop (`edit` / `repaint` / `cover`); shows time range picker or strength slider accordingly |
| `VersionTimeline` | In repaint/cover mode, highlights the source generation's version; allows switching |
| `GenerationSettings` | No changes — already reusable |
| `RepaintDialog` | **Removed** — replaced by editor mode |
| `CoverDialog` | **Removed** — replaced by editor mode |
| `GenerationsList` | Repaint/cover actions set mode state instead of opening modals |
| Editor stores | Track repaint/cover mode, source generation ID, selected time range |

**Backend:**

| File | Change |
|------|--------|
| `generation_api.py` | Repaint endpoint already accepts `version_id` via the job — just needs to use the user-selected version instead of the source generation's version |
| `RepaintRequest` | Add optional `version_id` field (defaults to source generation's version) |
| `CoverRequest` | Add optional `version_id` field |
| `jobs.py` | No changes — already loads version by ID |

### API Changes

**RepaintRequest** gains `version_id: str | None = None`:
- `None` → use the source generation's version (current behavior)
- Set → use that version's lyrics/prompt/settings instead

Same for **CoverRequest**.

The worker already receives `version_id` as a parameter and loads it from DB. The only change is allowing the API to pass a different version than the source generation's.

### Editor State

New state in the editor store or SongDetailView:

```typescript
type EditorMode =
  | { kind: 'edit' }
  | { kind: 'repaint'; sourceGeneration: GenerationItem; startPercent: number; endPercent: number }
  | { kind: 'cover'; sourceGeneration: GenerationItem; strength: number };
```

When `mode.kind !== 'edit'`:
- Version selector defaults to `sourceGeneration.version_id` but is changeable
- "Generate" button shows "Repaint" / "Cover" and calls the appropriate API
- Exiting mode (cancel, success, or switching songs) resets to `{ kind: 'edit' }`

### What NOT to Change

- The backend repaint/cover logic stays the same — it's already correct
- Generation params storage stays the same — each generation records what was actually used
- The version model stays the same — no schema changes
- Scoring, sharing, pick/keep — unaffected

### Migration from Modals

1. Remove `RepaintDialog.svelte` and `CoverDialog.svelte`
2. Remove `repaintTarget` and `coverTarget` state from SongDetailView
3. Add `editorMode` state to SongDetailView (or editor store)
4. Generation actions `repaint(gen)` and `cover(gen)` set `editorMode` instead of opening modals
5. SongEditor receives mode and renders time range / strength controls conditionally
6. Submit handler reads from editor state instead of modal callback

### Open Questions

- Should the time range picker be a waveform visualization or keep the simple percentage sliders? Waveform is better UX but more work.
- Should repaint mode lock the song selection (prevent switching songs while in repaint mode)?
- Should we show the source generation's audio player inline in the editor so the user can listen while editing the repaint section?
