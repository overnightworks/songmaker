# Generation-Centric Editing

## Problem

Generate, repaint, and cover all produce a generation from lyrics + prompt + params. The only difference is whether there's source audio and what to do with it. But the current UI treats them as completely separate workflows: generate lives in the editor, repaint/cover live in disconnected modal dialogs with duplicated controls and no access to version selection or generation settings.

Additionally, `src_generation_id` is not persisted — the backend uses it to find the wav file, then discards it. There's no record of which generation was the source for a repaint/cover. Provenance is lost.

Finally, the generation detail is an inline sub-view within the song's Generations tab, sharing the song's header actions (share, playlist, delete). This creates a mixed-context header — song actions visible while the user is focused on a generation. Every other entity (album, song) gets its own view with a consistent header. Generations are the exception.

## Design

Two changes:

1. **Generation gets its own view** — consistent with album and song views. Same header pattern (title + entity actions + back breadcrumb), same navigation model (click to drill in, breadcrumb to go back).

2. **Source generation as optional editor input** — repaint and cover are just "generate with a source generation attached." The editor gains one optional input. Everything else stays as-is.

## Navigation Hierarchy

Every level follows the same pattern: back breadcrumb to parent, entity title, entity-level actions in the header.

```
Album view                 Song view                    Generation view
┌────────────────┐         ┌─────────────────────┐      ┌──────────────────────┐
│ KREISBRAU      │         │ ← Kreisbräu         │      │ ← Null Ouvert        │
│ [Share][Delete]│ click → │ NULL OUVERT          │ click│ GENERATION #24       │
│                │  song   │ [Share][Playlist]    │ gen →│ [Share][Playlist]    │
│ • Null Ouvert  │         │ [Delete]             │      │ [Pick][Keep][Score]  │
│ • Zwei Null    │         │                      │      │ [Delete]             │
│                │         │ [Generations][Edit]  │      │ [Use as Source]      │
│                │         │ [Co-Writer]          │      │                      │
│                │         │                      │      │ ▶ ━━━━━━━━━━━ 3:12   │
│                │         │ Gen #24  ★ ♡        │      │                      │
│                │         │ Gen #23  ★          │      │ SCORES               │
│                │         │ Gen #22             │      │ ...                  │
│                │         │                      │      │ RATING               │
│                │         │                      │      │ ...                  │
│                │         │                      │      │ PARAMETERS           │
│                │         │                      │      │ ...                  │
│                │         │                      │      │ LINEAGE              │
│                │         │                      │      │ src → Gen #20 (v2)   │
└────────────────┘         └─────────────────────┘      └──────────────────────┘
```

### Generation view

A standalone view, rendered by `+page.svelte` when a generation is selected (same pattern as `SongDetailView` for songs and `AlbumDetailView` for albums). Not a sub-view within the song.

**Header:** Back breadcrumb ("← Song Title"), generation title ("Generation #24"), entity-level actions (share, add to playlist, pick, keep, score, delete, use as source). Same positions as song/album header actions.

**Content:** Single scrollable view (no tabs needed — a generation is simpler than a song):
- Audio player
- Scores section
- Rating section
- Parameters section
- Lineage section (source chain, clickable)

**"Use as source"** is a header action in the generation view. Clicking it navigates back to the song view's Edit tab with the source generation attached.

### Navigation store changes

The navigation store already tracks `selectedGenerationId`. Currently, selecting a generation keeps you in the song view (it's an inline sub-view). The change: selecting a generation navigates to the generation view, and the song view's Generations tab becomes purely the list.

```typescript
// +page.svelte render logic (simplified)
{#if selectedGeneration}
  <GenerationView />
{:else if song}
  <SongDetailView />
{:else if selectedAlbum}
  <AlbumDetailView />
{/if}
```

URL handling follows the same pattern as songs: `/?song=xxx&gen=yyy`. Back button (browser) returns to the song view.

## Song View (with source attachment)

### No Source (Standard Generate)

The song view, unchanged except: Generations tab is now purely the list (no inline detail). The Generate button and controls live in the header:

```
┌──────────────────────────────────────────┐
│ ← Kreisbräu                             │
│ NULL OUVERT              [Save][Generate]│
│ [Share][Playlist][Delete] ×1 ▾  model ▾ │
│                                          │
│ [Generations]  [Edit]  [Co-Writer]       │
│                                          │
│ [Version Timeline: v1  v2  v3  v4  v5]  │
│                                          │
│ Lyrics: [textarea]                       │
│ Prompt: [input]                          │
│ [BPM] [Duration] [Key]                   │
│ [Generation Settings]                    │
└──────────────────────────────────────────┘
```

### Source Attached — Repaint

User clicked "Use as source" in the generation view. Navigated back to song view's Edit tab. Header action changes from [Generate] to [Repaint]. Source bar and waveform picker appear at the top of the editor:

```
┌──────────────────────────────────────────┐
│ ← Kreisbräu                             │
│ NULL OUVERT             [Save] [Repaint] │
│ [Share][Playlist][Delete] ×1 ▾  model ▾ │
│                                          │
│ [Generations]  [Edit]  [Co-Writer]       │
│                                          │
│ ┄ Source: Gen #24 (v3) ┄┄┄┄┄┄ ▶ ┄┄ [×] │
│ [Repaint ● / Cover ○]                    │
│                                          │
│ [═══▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░══]           │
│  0:42 ────────────── 1:18                │
│                                          │
│ [Version Timeline: v1  v2  v3  v4  v5]  │
│                                          │
│ Lyrics: [textarea]                       │
│ Prompt: [input]                          │
│ [BPM] [Duration] [Key]                   │
│ [Generation Settings]                    │
└──────────────────────────────────────────┘
```

### Source Attached — Cover

Same source bar, toggle switched to cover. Strength slider instead of waveform. Header shows [Cover]:

```
┌──────────────────────────────────────────┐
│ ← Kreisbräu                             │
│ NULL OUVERT              [Save] [Cover]  │
│ [Share][Playlist][Delete] ×1 ▾  model ▾ │
│                                          │
│ [Generations]  [Edit]  [Co-Writer]       │
│                                          │
│ ┄ Source: Gen #24 (v3) ┄┄┄┄┄┄ ▶ ┄┄ [×] │
│ [Repaint ○ / Cover ●]                    │
│                                          │
│ Free ←[━━━━━━━━━●━━━━] 70%→ Strict      │
│                                          │
│ [Version Timeline: v1  v2  v3  v4  v5]  │
│                                          │
│ Lyrics: [textarea]                       │
│ Prompt: [input]                          │
│ [BPM] [Duration] [Key]                   │
│ [Generation Settings]                    │
└──────────────────────────────────────────┘
```

Clicking [×] clears the source, hides the source bar and mode-specific controls, header reverts to [Generate].

## Header Action Logic

The current header swaps between Save (when dirty on Edit tab) and Generate (otherwise). This changes:

**Current behavior:** Save and Generate are mutually exclusive — Generate disappears when the editor is dirty, forcing the user to save first. Generate is visible on all tabs.

**New behavior:** Save and the action button coexist when both apply. The action button auto-saves before submitting if the editor is dirty. This is a behavior change for standard generate too, not just repaint/cover.

The action button label follows the state:
- No source → **[Generate]**
- Source + repaint toggle → **[Repaint]**
- Source + cover toggle → **[Cover]**

### Tab-aware visibility

The action buttons (Save, Generate/Repaint/Cover, count selector, model selector) only show on the two creative tabs — Edit and Co-Writer. The Generations tab is the review surface; it shows only song-level actions (share, playlist, delete).

| Tab | Header actions |
|-----|---------------|
| Edit (clean, no source) | `[Generate] ×N model` |
| Edit (dirty, no source) | `[Save] [Generate] ×N model` |
| Edit (clean, source) | `[Repaint/Cover] ×N model` |
| Edit (dirty, source) | `[Save] [Repaint/Cover] ×N model` |
| Co-Writer (clean) | `[Generate/Repaint/Cover] ×N model` |
| Co-Writer (dirty) | `[Save] [Generate/Repaint/Cover] ×N model` |
| Generations | Song-level actions only (share, playlist, delete) |

**Why Co-Writer gets the action buttons:** The Co-Writer proposes changes via `songmaker` blocks that the user applies to the editor draft. After applying, the editor is dirty and the user wants to hear the result immediately — "here's new lyrics, let's generate" should be one click, not a tab switch.

**Why Generations doesn't:** It's the review surface — listing generations. To act on a generation, click it to navigate to the generation view. No blind submissions.

Count selector (×1, ×2, etc.) and model selector remain visible for all modes. Multiple repaints/covers of the same source is a valid workflow.

## Source Bar

Compact bar at the top of the editor when a source generation is attached:

- **Label:** "Source: Gen #24 (v3)" — generation number + version it was created from
- **Play button (▶):** Plays the source generation's audio via the global player. The user can listen while editing lyrics/params.
- **Dismiss (×):** Clears the source, returns to standard generate mode.
- **Repaint/Cover toggle:** Two-option segmented control. Determines which mode-specific controls appear and what the header action button does.

## State Ownership

All source-related state lives in SongDetailView, passed down to SongEditor as props:

```typescript
// SongDetailView state
let sourceGeneration = $state<GenerationItem | null>(null);
let sourceMode = $state<'repaint' | 'cover'>('repaint');
let repaintStart = $state(0);
let repaintEnd = $state(1);
let coverStrength = $state(0.7);
```

SongDetailView owns the state because:
- The header reads `sourceGeneration` + `sourceMode` to determine the action button label
- The submit handler in SongDetailView reads all source state for the API call
- SongEditor renders the source bar and mode-specific controls but doesn't own the state

SongEditor receives:

```typescript
interface Props {
  ondeleteversion: (versionId: string, deleteGenerations: boolean) => void;
  selectedModel?: string | null;
  sourceGeneration?: GenerationItem | null;
  sourceMode?: 'repaint' | 'cover';
  repaintStart?: number;
  repaintEnd?: number;
  coverStrength?: number;
  onrepaintrangechange?: (start: number, end: number) => void;
  oncoverstrengthchange?: (strength: number) => void;
  onsourcemodechange?: (mode: 'repaint' | 'cover') => void;
  onsourceclear?: () => void;
}
```

## Waveform Range Picker (Repaint Only)

Replaces the current percentage sliders. Provides visual context for time range selection.

### Rendering

1. Decode the source generation's audio via Web Audio API (`AudioContext.decodeAudioData`). The audio URL comes from the same endpoint the global player uses (generation's `mp3_path` served via the API).
2. Extract peak amplitude data from the decoded buffer, downsample to 200–400 bars.
3. Render as SVG or Canvas. Selected region in accent color, unselected regions dimmed.

### Interaction

- Two draggable handles (start/end) overlaid on the waveform.
- Drag to select the section to repaint.
- Handles snap to 0.5s increments.
- Touch-friendly: 44px minimum hit target per handle.
- Time display below: `0:42 ——— 1:18`, updates live during drag.

### Playback

A small play button on the waveform bar plays only the selected range via the global audio player (not a separate audio context). Lets the user hear exactly what will be repainted.

### Mobile

Full-width waveform, touch-drag handles, ~80px height. Compact enough to stay above the editor without dominating scroll.

### Props

```typescript
interface WaveformRangePickerProps {
  audioUrl: string;
  duration: number;
  startPercent: number;   // 0–1
  endPercent: number;     // 0–1
  onchange: (start: number, end: number) => void;
}
```

## Cover Strength Slider

Standard range input with semantic labels:

```
Free ←[━━━━━━━━━●━━━━] 70%→ Strict
```

- 0% = free reinterpretation (loose structure)
- 100% = strict structure preservation
- Default: 70%

## Submit Flow

### Auto-Save Before Submit

Every generation must be tied to a saved version. If the editor is dirty when the user hits the action button:

1. Auto-save → creates a new version with the current editor content
2. Submit the generate/repaint/cover job with that version's ID

If the editor is clean, submit with the current version's ID.

This means:
- No `lyrics`/`prompt` override fields in the request body — the version has everything
- Every generation has clean provenance: version_id + optional source generation + mode params
- No orphaned state, no "which lyrics were actually used?" ambiguity

### Source Stays Attached After Submit

After a successful repaint/cover submit, the source generation remains attached. The user can immediately adjust the time range or strength and submit again (iterative refinement of the same source). The user clears the source manually with [×] when done.

### What Gets Sent

**Generate:**
```json
{ "version_id": "v5", "count": 1, "model": "...", "seed": null }
```

**Repaint:**
```json
{
  "src_generation_id": "gen24",
  "version_id": "v5",
  "repainting_start": 0.35,
  "repainting_end": 0.55,
  "model": "...",
  "seed": null,
  "count": 2
}
```

**Cover:**
```json
{
  "src_generation_id": "gen24",
  "version_id": "v5",
  "audio_cover_strength": 0.7,
  "model": "...",
  "seed": null,
  "count": 1
}
```

## Generation Provenance

### The gap: `src_generation_id` is not persisted

Currently, the backend receives `src_generation_id` in RepaintRequest/CoverRequest, uses it to locate the wav file, then discards it. The resulting generation has no record of which generation was its source. `StoredGenerationParams` stores `repainting_start/end` and `audio_cover_strength` but not the source.

### Fix: new column on Generation

```python
# db/models.py — Generation model
src_generation_id: Mapped[str | None] = mapped_column(
    ForeignKey("generations.id", ondelete="SET NULL"), nullable=True,
)
src_generation: Mapped[Generation | None] = relationship(
    remote_side=[id], foreign_keys=[src_generation_id],
)
```

`SET NULL` on delete — if the source generation is deleted, the derived generation survives (its audio is independent). The FK is nullable (null for standard generations, set for repaint/cover).

### Storing it

The worker's `_run_single_generation` creates the generation record via `create_generation()`. Currently receives `song_id`, `version_id`, `mp3_path`, `seed`, `generation_params`, `wav_path`, `model_mode`. Add `src_generation_id` as a parameter, threaded through from the repaint/cover params.

The `src_generation_id` must be passed from the API endpoint → `repaint_params`/`cover_params` dict → worker → `_run_single_generation` → `create_generation()`.

### API response

Add to `GenerationResponse` and `GenerationItem`:

```python
# api_models — GenerationResponse
src_generation_id: str | None = None
src_generation_number: int | None = None  # for display: "Repainted from Gen #24"
```

```typescript
// types.ts — GenerationItem
src_generation_id: string | null;
src_generation_number: number | null;
```

### Provenance chain

Every generation now records:
- `version_id` → the version whose lyrics/prompt/params were used (always set)
- `src_generation_id` → the source audio generation (set for repaint/cover, null for standard)
- `generation_params.task_type` → "repaint", "cover", or null
- `generation_params.repainting_start/end` → time range (repaint only)
- `generation_params.audio_cover_strength` → strength (cover only)

Chains are followable:
```
Gen #35 (cover, v6, strength 0.7, src → Gen #30)
  └→ Gen #30 (repaint, v5, 0:42–1:18, src → Gen #24)
      └→ Gen #24 (original, v3, src → null)
```

### Lineage in the generation view

The generation view shows the source lineage. For repainted/covered generations:

```
Source: Gen #24 (v3) → Gen #30 (v5, repaint) → this
```

Each link is clickable, navigating to that generation's view.

## Attaching a Source

From the generation view, the user clicks **"Use as source"** in the header. This:

1. Stores the source generation in SongDetailView state
2. Navigates back to the song view
3. Switches to the Edit tab
4. Source bar appears at the top of the editor
5. Repaint is the default toggle selection

Seed pinning works as before — orthogonal to source attachment. A pinned seed applies to the next generate/repaint/cover regardless.

## Save Button

Save always means save — creates a new version from the current editor content. Unaffected by whether a source is attached. This is a feature: the user can save repaint tweaks as a version even if they decide not to repaint.

## Workflow Examples

**Standard generate:**
1. Edit lyrics and prompt on the Edit tab
2. Hit [Generate] in the header
3. If dirty, auto-saves first
4. New generation appears in the list

**Repaint a section:**
1. Click generation #24 in the list → navigates to generation view
2. Listen to the audio, notice the bridge sounds off
3. Click [Use as Source] in the header → navigates back to song Edit tab, source bar appears
4. Drag waveform handles to select 1:42–2:18
5. Play the selected range to confirm
6. Tweak the bridge lyrics in the editor
7. Hit [Repaint] in the header → auto-saves, submits repaint job
8. New generation appears in the list, source stays attached for further repaints

**Cover with different style:**
1. Click generation #24 → generation view
2. Click [Use as Source] → back to song Edit tab
3. Toggle to Cover in the source bar
4. Set strength to 60%
5. Change the style prompt
6. Hit [Cover]

**Multiple repaints of the same source:**
1. Click generation #24 → generation view → [Use as Source] → Edit tab
2. Select time range 1:42–2:18, hit [Repaint] ×2
3. Listen to results, adjust range to 0:30–1:00, hit [Repaint] ×1
4. Click [×] when done iterating

**Quick repaint without edits:**
1. Click generation #24 → generation view → [Use as Source] → Edit tab
2. Select time range on the waveform
3. Hit [Repaint] → no save needed (editor is clean), submits with current version

**Decide not to repaint:**
1. Click generation #24 → generation view → [Use as Source] → Edit tab
2. Change your mind
3. Click [×] on the source bar → back to normal
4. Editor content is untouched

**Browse generation details:**
1. Click generation #24 in the list → navigates to generation view
2. Review scores, listen to audio, check parameters
3. Click "← Null Ouvert" to go back to song view

## What Changes

### Frontend

| Component | Change |
|-----------|--------|
| `+page.svelte` | Add `GenerationView` to render logic: `selectedGeneration` → `<GenerationView />`, before the `song` check. |
| `GenerationView` | **New component.** Standalone view for a generation: header (back breadcrumb, title, entity actions), audio player, scores, rating, params, lineage. Replaces the inline GenerationDetail within SongDetailView. |
| `SongDetailView` | Remove inline GenerationDetail rendering and `activeGen` conditional. Generations tab is purely the list. `sourceGeneration` + `sourceMode` + range/strength state replaces `repaintTarget` / `coverTarget`. Header action buttons tab-aware. Save and action button coexist when dirty. Auto-save before submit. |
| `SongEditor` | New props: `sourceGeneration`, `sourceMode`, range/strength values + change callbacks. Renders source bar, repaint/cover toggle, waveform picker or strength slider. No submit logic (stays in SongDetailView). |
| `WaveformRangePicker` | **New component.** Waveform visualization + draggable range handles + selected-range playback via global player. |
| `GenerationDetail` | Refactored into `GenerationView`. The inline component is removed from SongDetailView. |
| `GenerationsList` | Click navigates to generation view (instead of showing inline detail). |
| `RepaintDialog` | **Deleted.** |
| `CoverDialog` | **Deleted.** |
| `GenerationItem` type | Add `src_generation_id`, `src_generation_number` fields. |
| Navigation store | `selectGeneration()` pushes URL with gen param (`/?song=xxx&gen=yyy`). `backToSong()` function for generation view → song view. Handle browser back. |
| Editor store | No changes. |
| Generation actions context | Replace `repaint` / `cover` callbacks with `useAsSource` callback that navigates to song Edit tab with source attached. |

### Backend

| File | Change |
|------|--------|
| `db/models.py` | Add `src_generation_id` FK column on Generation (self-referential, nullable, `SET NULL` on delete). |
| Alembic migration | New migration for `src_generation_id` column. |
| `db/queries/generations.py` | `create_generation()` accepts `src_generation_id` parameter. |
| `RepaintRequest` | Add `version_id: str \| None = None`. Add `count: int = 1`. |
| `CoverRequest` | Add `version_id: str \| None = None`. Add `count: int = 1`. |
| `generation_api.py` | Thread `version_id` through to the job. Thread `src_generation_id` through `repaint_params`/`cover_params` to the worker. |
| `jobs.py` | `_run_single_generation` passes `src_generation_id` to `create_generation()`. Receives it via `repaint_params`/`cover_params`. |
| `music_worker.py` | No changes (already passes `repaint_params`/`cover_params` through). |
| `GenerationResponse` | Add `src_generation_id`, `src_generation_number` fields. |
| `from_orm()` | Resolve `src_generation_number` from the relationship. |

### API Changes

`RepaintRequest` and `CoverRequest` gain:
- `version_id: str | None = None` — when set, use that version's lyrics/prompt/params instead of the source generation's version
- `count: int = 1` — number of generations to produce

The `lyrics` and `prompt` fields remain on the request models for backward compatibility but the frontend stops using them. The version is the single source of truth.

## What Does NOT Change

- Editor store (`editor.ts`) — `loadVersion()` already handles everything
- GenerationSettings component — already reusable, no changes
- Version model — no schema changes
- Backend worker logic — already receives repaint/cover params and routes correctly
- Scoring, sharing, pick/keep — unaffected

## Migration Steps

1. **Backend:** Add `src_generation_id` column to Generation model + Alembic migration
2. **Backend:** Thread `src_generation_id` through worker → `create_generation()`
3. **Backend:** Add `src_generation_id` / `src_generation_number` to `GenerationResponse`
4. **Backend:** Add `version_id` and `count` to `RepaintRequest` / `CoverRequest`, wire through endpoint logic
5. **Frontend:** Run `python scripts/generate_types.py` to pick up new GenerationItem fields
6. **Frontend:** Build `WaveformRangePicker` component
7. **Frontend:** Extract `GenerationDetail` into standalone `GenerationView` component
8. **Frontend:** Update navigation store: `selectGeneration()` navigates to generation view with URL, add `backToSong()`, handle browser back/forward
9. **Frontend:** Update `+page.svelte` render logic to show `GenerationView` when generation selected
10. **Frontend:** Remove inline GenerationDetail from `SongDetailView`, Generations tab becomes list-only
11. **Frontend:** Update `GenerationsList` click handler to navigate to generation view
12. **Frontend:** Add source state to `SongDetailView`, replace `repaintTarget` / `coverTarget`
13. **Frontend:** Rework header: Save + action button coexist when dirty, action label context-aware, tab-aware visibility, auto-save before submit
14. **Frontend:** Add source bar + repaint/cover toggle + mode-specific controls to `SongEditor` as props
15. **Frontend:** Add "Use as source" action to `GenerationView` header, wires to song view with source attached
16. **Frontend:** Update generation actions context: replace `repaint`/`cover` with `useAsSource`
17. **Frontend:** Delete `RepaintDialog`, `CoverDialog`
18. **Frontend:** Wire waveform playback through global audio player
19. **Frontend:** Show source lineage in `GenerationView` with clickable chain

## Mobile

- Generation view is a full-screen scrollable view (same as song view on mobile)
- Source bar is a compact single line (~40px)
- Waveform picker is full-width, ~80px, touch-drag handles with 44px targets
- Strength slider is a standard range input, works natively on touch
- No modals, no overlays, no nested tabs
- Navigation between views uses standard back gesture / breadcrumb
