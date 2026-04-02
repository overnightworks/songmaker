# Plan: +page.svelte Decomposition + Generation Action Context (U1+B7)

## Problem

`+page.svelte` is 1470 lines with ~94 lines of imports, 7 store subscriptions, 15+ API functions, 10+ child components, and ~25 event handler functions. It is the single orchestrator for the entire app — every user action flows through it. Adding a feature means touching this file. Debugging means reading 600+ lines of reactive logic.

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

### Step 2: Extract view components

The `main-content` area is a view router — it switches between 4 mutually exclusive views depending on what's selected. Each becomes its own component with its own handlers, template, and CSS.

#### `SongDetailView.svelte`
**Owns:** Song header (title, back button, generate/save actions, job indicators, share), tab bar, generation list/detail, editor, co-writer chat, repaint/cover dialogs
**Sets context:** `GenerationActions` (from step 1)
**Reads:** `selectedSong`, `selectedGeneration`, editor stores, `activeJobs`, `activeModels`, navigation stores
**Local state (moved from +page.svelte):**
- `pinnedSeed: number | null`
- `repaintTarget: GenerationItem | null`
- `coverTarget: GenerationItem | null`
- `genCount: number`
- `selectedModel: string | null`
**Handlers (moved from +page.svelte):** `onGenerate`, `onSave`, `onDeleteVersion`, `onPick`, `onKeep`, `onRate`, `onScore`, `onDeleteGeneration`, `onRepaintSubmit`, `onCoverSubmit`, `onSongShareEnable/Disable`, `onSongCleanup`, `onDeleteSong`, `onGenShareEnable/Disable`, `onVersionClick`
**CSS (moved from +page.svelte):** `.detail-panel`, `.detail-header`, `.song-title*`, `.song-album`, `.detail-actions`, `.save-btn`, `.generate-btn`, `.gen-count-select`, `.model-select`, `.pinned-seed`, `.job-*`, `.gen-detail-wrapper`, `.back-btn`, `.back-arrow`, `.tab-bar`, `.tab-btn`, `.chat-tab`, `.chat-active` overrides

This is the biggest extraction — ~200 lines of script, ~200 lines of template, ~300 lines of CSS.

#### `AlbumDetailView.svelte`
**Owns:** Album header (title, back button, play/share/overflow), album song list
**Reads:** `albumList`, `songList`, `selectedAlbumId`
**Handlers (moved from +page.svelte):** `onAlbumShareEnable/Disable`, `onAlbumCleanup`, `onAlbumDelete`
**CSS (moved from +page.svelte):** `.album-song-list`, `.album-song-row`, `.album-song-title`, `.album-song-meta`

Reuses shared CSS classes (`.detail-panel`, `.detail-header`, `.back-btn`) — these either move to a shared stylesheet or each view duplicates the few lines it needs. Prefer duplication over a shared import for ~10 lines of layout CSS.

#### `PlaylistDetailView.svelte`
**Owns:** Playlist header (title, back button, play/share/overflow), entry list with reorder/remove
**Reads:** `selectedPlaylistDetail`
**Handlers (moved from +page.svelte):** `onPlaylistShareEnable/Disable`, `onPlaylistDelete`, `onPlaylistRename`, `onRemovePlaylistEntry`, `onMovePlaylistEntry`
**CSS (moved from +page.svelte):** `.playlist-entry-row`, `.playlist-entry-controls`, `.move-btn`, `.playlist-entry-info`, `.remove-btn`, `.empty-tab`

#### Remaining in `+page.svelte`
After extracting all four views, the page becomes:

**Script (~50 lines):**
- Imports (views, stores, API, components)
- `loading`, `loadError` state
- `playlistPickerFor` state (global overlay)
- `onMount` — fetch albums/songs/playlists/models
- `onAddToPlaylist` handler (used by picker modal across views)
- Derived: `song`, `selectedAlbum`, `playlistDetail`, `showCreate`

**Template (~40 lines):**
```svelte
{#if loading}
  <div class="loading">...</div>
{:else if loadError}
  <div class="error">...</div>
{:else}
  <aside class="sidebar">
    <SongList onNewSong={() => showCreate = !showCreate} />
  </aside>
  <main class="main-content">
    {#if showCreate}
      <CreateForm albums={$albumList} />
    {:else if song}
      <SongDetailView {song} {playlistPickerFor} onplaylistpick={...} />
    {:else if selectedAlbum}
      <AlbumDetailView album={selectedAlbum} {playlistPickerFor} onplaylistpick={...} />
    {:else if playlistDetail}
      <PlaylistDetailView playlist={playlistDetail} />
    {:else}
      <div class="empty-state">...</div>
    {/if}
  </main>
{/if}
{#if playlistPickerFor}
  <PlaylistPicker onselect={onAddToPlaylist} onclose={() => playlistPickerFor = null} />
{/if}
<ToastContainer />
```

**CSS (~80 lines):**
- `.sidebar`, `.main-content`, `.loading`, `.error`, `.empty-state`, `.empty-waveform`, `.wave-bar`, `@media (max-width: 768px)` responsive rules

Target: **~170 lines total**.

### Step 3: Simplify ClaudeChat props

After mutation centralization (editor-state-refactor Part B), `ClaudeChat` calls `replaceSongInList()` and `handleApply()` directly from store imports — no callbacks needed. Current 8 props reduce to:
- `songId` — which song's chat to show
- `visible` — whether the tab is active (controls scroll/focus behavior)

`allSongs`, `currentAlbumId`, `versions` can be read from stores directly inside the component. `onapply`, `oncreate`, `onnavigate` become direct store/navigation calls.

### Step 4: Hoist PlaylistPicker to page level

The `PlaylistPicker` modal is currently inlined in 3 places (song actions, album actions, generation detail). After decomposition, each view would need its own copy or a way to trigger the shared one. Solution: keep `playlistPickerFor` state and `PlaylistPicker` rendering in `+page.svelte`, pass a callback (`onplaylistpick`) or use a store to let views open it:

```ts
// lib/stores/playlists.ts (add to existing)
export const playlistPickerTarget = writable<{type: 'song'|'album'|'generation', id: string} | null>(null);
```

Views call `playlistPickerTarget.set(...)` to open the picker. `+page.svelte` reads the store and renders the modal. This avoids prop drilling the picker state into every view.

## CSS strategy

~550 lines of CSS currently in `+page.svelte`. After decomposition:

| Destination | CSS classes | ~Lines |
|---|---|---|
| `SongDetailView.svelte` | `.detail-panel`, `.detail-header`, `.song-title*`, `.save-btn`, `.generate-btn`, `.gen-*`, `.job-*`, `.tab-*`, `.chat-tab`, `.pinned-seed`, `.back-btn`, `.back-arrow`, `.share-link`, `.picker-anchor` | ~300 |
| `AlbumDetailView.svelte` | `.detail-panel`, `.detail-header`, `.back-btn`, `.album-song-*`, `.share-link`, `.picker-anchor` | ~60 |
| `PlaylistDetailView.svelte` | `.detail-panel`, `.detail-header`, `.back-btn`, `.playlist-entry-*`, `.move-btn`, `.remove-btn`, `.empty-tab`, `.share-link` | ~80 |
| `+page.svelte` (remains) | `.sidebar`, `.main-content`, `.loading`, `.error`, `.empty-state`, `.wave-*`, `@media` | ~80 |

Shared classes (`.detail-panel`, `.detail-header`, `.back-btn`, `.back-arrow`, `.share-link`) are used by all three views. Options:
1. **Duplicate** — each view copies the ~30 shared lines. Simple, no coupling, Svelte-idiomatic.
2. **Extract to `lib/styles/detail-panel.css`** — import in each view via `@import`. Reduces duplication but adds a dependency.

Prefer option 1 unless the shared CSS grows beyond ~40 lines.

## File changes

### New files
| File | Purpose |
|------|---------|
| `lib/contexts/generation-actions.ts` | Context type + set/get helpers |
| `lib/components/SongDetailView.svelte` | Song editing, generations, chat |
| `lib/components/AlbumDetailView.svelte` | Album header + song list |
| `lib/components/PlaylistDetailView.svelte` | Playlist header + entry list |

### Modified files
| File | Change |
|------|--------|
| `routes/+page.svelte` | Shrink from ~1470 to ~170 lines: layout shell + view router + global overlays |
| `components/GenerationDetail.svelte` | Remove 12 callback props, read from context |
| `components/GenerationsList.svelte` | Remove callback props, read from context |
| `components/ClaudeChat.svelte` | Remove callback props, read stores directly |
| `stores/playlists.ts` | Add `playlistPickerTarget` writable store |

## Order of operations

1. Create `generation-actions.ts` context (no existing code changes yet)
2. Create `SongDetailView.svelte` — move song detail logic, handlers, template, and CSS from `+page.svelte`. Set generation actions context here.
3. Update `GenerationDetail.svelte` and `GenerationsList.svelte` to use context instead of callback props
4. Create `AlbumDetailView.svelte` — move album detail logic, handlers, template, and CSS from `+page.svelte`
5. Create `PlaylistDetailView.svelte` — move playlist detail logic, handlers, template, and CSS from `+page.svelte`
6. Add `playlistPickerTarget` store, migrate playlist picker to page-level
7. Simplify `ClaudeChat.svelte` props (remove callbacks, use store/navigation imports)
8. Clean up `+page.svelte` — should be ~170 lines

Verify the app works after steps 2, 4, 5 (the three view extractions). Don't batch all extractions without intermediate checks.

## Risks

- **Shared CSS duplication**: Three views share `.detail-panel`, `.detail-header`, `.back-btn` styles. Duplicating ~30 lines per view is acceptable. If it drifts, extract to a shared CSS file later.
- **Svelte context lifecycle**: `setContext`/`getContext` only works during component initialization (top-level script). Cannot call `getContext` inside event handlers or `$effect`. The `GenerationActions` context must be read once at component init and stored in a local variable.
- **PlaylistPicker across views**: Currently rendered inline in song/album action menus. After decomposition, either hoist to page level (via store) or pass a callback prop. Store approach is cleaner.
- **Repaint/Cover dialogs**: These are global overlays triggered from generation detail. They move into `SongDetailView` since they only apply to songs — they need `selectedModel` and `song` which are local to that view.
- **Large diff**: This is a ~1200-line refactor across ~8 files. The intermediate verification points (after each view extraction) are critical.
- **Testing**: No component-level tests exist for `+page.svelte`. Store-level tests are unaffected. Manual verification after each step.

## Success criteria

- `+page.svelte` < 200 lines
- `GenerationDetail.svelte` has ≤ 3 props
- Each view component has a single clear responsibility — song, album, or playlist
- No callback prop drilling for generation actions (context handles it)
- `ClaudeChat.svelte` has ≤ 3 props
