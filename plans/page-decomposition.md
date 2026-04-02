# Plan: +page.svelte Decomposition + Generation Action Context (U1+B7)

## Problem

`+page.svelte` is 1498 lines with ~94 lines of imports, 7 store subscriptions, 15+ API functions, 10+ child components, and ~25 event handler functions. It is the single orchestrator for the entire app — every user action flows through it. Adding a feature means touching this file. Debugging means reading 600+ lines of reactive logic.

`GenerationDetail.svelte` takes 12 callback props because the parent must implement every generation action.

## Prerequisites

Complete [editor-state-refactor.md](editor-state-refactor.md) first — the mutation centralization (Part B) significantly reduces the number of `songList.update()` calls in `+page.svelte`, making decomposition cleaner.

## Solution

### Step 1: Extract generation actions into a context

Create `lib/contexts/generation-actions.ts`:

```ts
import { setContext, getContext } from 'svelte';

export interface GenerationActions {
  score: (genId: string) => Promise<void>;
  pick: (genId: string, picked: boolean) => Promise<void>;
  keep: (genId: string, kept: boolean) => Promise<void>;
  delete: (genId: string) => Promise<void>;
  rate: (genId: string, rating: number, notes: string) => Promise<void>;
  share: (genId: string) => Promise<ShareResult>;
  unshare: (genId: string) => Promise<void>;
  addToPlaylist: (playlistId: string, genId: string) => Promise<void>;
  pinSeed: (seed: number) => void;
  clickVersion: (versionId: string) => void;
  repaint: (gen: GenerationItem) => void;
  cover: (gen: GenerationItem) => void;
}

const KEY = 'generation-actions';

export function setGenerationActions(actions: GenerationActions) {
  setContext(KEY, actions);
}

export function getGenerationActions(): GenerationActions {
  return getContext(KEY);
}
```

Update `GenerationDetail.svelte` props from 12 callbacks to:
```ts
interface Props {
  generation: GenerationItem;
  scoring?: boolean;
}
```

The component calls `getGenerationActions()` internally.

Update `GenerationsList.svelte` similarly — reduce to `{ song, onselect }`.

### Step 2: Split +page.svelte into panel components

The page layout has three regions: sidebar (library), center (detail), right (chat). Extract each:

#### `LibraryPanel.svelte`
**Owns:** Album/song list display, create form, album actions (share, cleanup, delete)
**Reads:** `albumList`, `songList`, `selectedAlbumId`, `selectedSongId`, `filteredSongs`
**Emits:** `onselectsong`, `onselectalbum` (navigation events)
**Calls:** `fetchAlbums`, `fetchSongs`, `createAlbum`, `createSong`, `deleteAlbum`, `deleteSong`, `shareAlbum`, `cleanupAlbum`

#### `DetailPanel.svelte`
**Owns:** Song editor, generation list, generation detail, generation settings, version timeline
**Sets context:** `GenerationActions` (step 1)
**Reads:** `selectedSong`, `selectedGeneration`, editor stores, `activeJobs`
**Calls:** `generateSong`, `scoreGeneration`, `pickGeneration`, `keepGeneration`, `rateGeneration`, `deleteGeneration`, `shareGeneration`, `repaintGeneration`, `coverGeneration`

#### `ChatPanel.svelte`
Already mostly encapsulated in `ClaudeChat.svelte`. The thin wrapper in `+page.svelte` just passes props. After mutation centralization (Part B of editor refactor), `ClaudeChat` calls `replaceSongInList()` directly — no callback needed.

#### Remaining in `+page.svelte`
- Layout shell: renders three panels, `PlayerBar` (fixed bottom)
- Cross-panel coordination:
  - Song selection: `LibraryPanel` emits → page updates `selectedSongId` → `DetailPanel` reacts
  - Job tracking: `trackJob()` / `removeJob()` (stays in page, passed down or via context)
  - Playlist picker modal (stays in page — it's a global overlay)
  - Initial data load (`onMount` → fetch albums/songs)

### Step 3: Move initial data loading

The `onMount` fetch of albums and songs stays in `+page.svelte` (it's app-level initialization). The fetched data is set into stores, and panels read from stores.

## File changes

### New files
| File | Purpose |
|------|---------|
| `lib/contexts/generation-actions.ts` | Context type + set/get helpers |
| `lib/components/LibraryPanel.svelte` | Sidebar: album/song list, create, album actions |
| `lib/components/DetailPanel.svelte` | Center: editor, generations, settings |

### Modified files
| File | Change |
|------|--------|
| `routes/+page.svelte` | Shrink from ~1500 to ~200 lines: layout shell + cross-panel coordination |
| `components/GenerationDetail.svelte` | Remove 12 callback props, read from context |
| `components/GenerationsList.svelte` | Remove callback props, read from context |
| `components/ClaudeChat.svelte` | Remove `onapply`/`oncreate` callbacks, call store helpers directly |

## Order of operations

1. Create `generation-actions.ts` context (no existing code changes yet)
2. Create `DetailPanel.svelte` — move generation/editor/scoring logic from `+page.svelte`
3. Update `GenerationDetail.svelte` and `GenerationsList.svelte` to use context
4. Create `LibraryPanel.svelte` — move album/song list logic from `+page.svelte`
5. Simplify `ClaudeChat.svelte` props (remove callbacks, use store helpers)
6. Clean up `+page.svelte` — should be ~200 lines

## Risks

- **Component communication**: Cross-panel events (e.g., "song just generated, refresh detail") currently work because everything is in one component. After splitting, need explicit store subscriptions or events. The existing store architecture already supports this — panels just read from stores.
- **Playlist picker modal**: Currently lives in `+page.svelte` with state. Keep it there (it's a global overlay) or extract to its own modal component.
- **Testing**: Vitest component tests (if any exist for `+page.svelte`) will need updating. Store-level tests should be unaffected.
- **Large diff**: This is a ~1000-line refactor. Do it in one focused session to avoid partial states.

## Success criteria

- `+page.svelte` < 250 lines
- `GenerationDetail.svelte` has ≤ 3 props
- No direct `songList.update()` / `albumList.update()` calls outside `player.ts`
- Each panel component has a single clear responsibility
