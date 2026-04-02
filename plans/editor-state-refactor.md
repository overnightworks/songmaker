# Plan: Editor State Refactor + Store Mutation Centralization (U2+B6)

## Problem

Two related issues:

1. **Editor dual-state**: `editor.ts` maintains 12 parallel writable stores (`editLyrics`/`savedLyrics`, `editPrompt`/`savedPrompt`, etc.). The `isDirty` derived store checks all 12. `loadVersion()` updates 6 stores sequentially with no atomicity — if it fails midway, the editor is in an inconsistent state.

2. **Store mutation coupling**: `songList` from `player.ts` is mutated from 4 different modules:
   - `editor.ts` (lines 177, 196) — after save, after version delete
   - `jobs.ts` (line 112) — after job completion
   - `+page.svelte` (~15 locations) — pick, keep, rate, share, delete, cleanup
   - `ClaudeChat.svelte` — after applying cross-song changes

This makes it impossible to trace "why did the song list change?" without reading 4 files.

## Solution

### Part A: Editor state consolidation

Replace the 12 parallel stores with a single `editorState` store:

```ts
interface SongData {
  lyrics: string;
  prompt: string;
  bpm: number;
  duration: number;
  key: string;
  genParams: VersionGenerationParams | null;
}

const editorState = writable<{ saved: SongData; draft: SongData }>({
  saved: EMPTY_SONG_DATA,
  draft: EMPTY_SONG_DATA,
});

const isDirty = derived(editorState, (s) => !deepEqual(s.saved, s.draft));
```

**Benefits:**
- `loadVersion()` becomes a single `editorState.set(...)` — atomic, no partial updates
- `isDirty` has one dependency, not 12
- `handleSave()` updates `saved` to match `draft` in one operation
- Diff state (`diffBase`, `diffTarget`, etc.) stays separate — it's display-only

**Migration steps:**
1. Create `SongData` interface and `EMPTY_SONG_DATA` constant
2. Replace the 12 writable stores with one `editorState` writable
3. Export derived accessors for components that need individual fields:
   ```ts
   export const editLyrics = derived(editorState, s => s.draft.lyrics);
   // etc.
   ```
4. For write access, export mutation functions:
   ```ts
   export function setDraftLyrics(lyrics: string) {
     editorState.update(s => ({ ...s, draft: { ...s.draft, lyrics } }));
   }
   ```
5. Update `SongEditor.svelte` and `GenerationSettings.svelte` to use the new API
6. Update `loadSongData()`, `loadVersion()`, `handleSave()`, `handleApply()`

### Part B: Centralize song/album list mutations

Add mutation functions to `player.ts`:

```ts
export function updateSongInList(songId: string, updater: (s: SongItem) => SongItem): void {
  songList.update(list => list.map(s => s.id === songId ? updater(s) : s));
}

export function replaceSongInList(song: SongItem): void {
  songList.update(list => list.map(s => s.id === song.id ? song : s));
}

export function removeSongFromList(songId: string): void {
  songList.update(list => list.filter(s => s.id !== songId));
}

export function updateAlbumInList(albumId: string, updater: (a: AlbumItem) => AlbumItem): void {
  albumList.update(list => list.map(a => a.id === albumId ? updater(a) : a));
}

export function removeAlbumFromList(albumId: string): void {
  albumList.update(list => list.filter(a => a.id !== albumId));
}
```

Then replace all direct `songList.update(list => list.map(...))` calls across the codebase with these functions:
- `editor.ts`: `handleSave()` → `replaceSongInList(updated)`
- `jobs.ts`: `refreshSongData()` → `replaceSongInList(song)`
- `+page.svelte`: all 15 mutation sites → corresponding helper
- `ClaudeChat.svelte`: → `replaceSongInList(song)`

## Files to modify

| File | Change |
|------|--------|
| `stores/editor.ts` | Rewrite: single `editorState` store, export derived + setters |
| `stores/player.ts` | Add: mutation helpers (`updateSongInList`, etc.) |
| `stores/jobs.ts` | Replace: direct `songList.update()` → `replaceSongInList()` |
| `components/SongEditor.svelte` | Update: read from derived stores, write via setters |
| `components/GenerationSettings.svelte` | Update: read/write via new API |
| `components/ClaudeChat.svelte` | Replace: direct `songList.update()` → `replaceSongInList()` |
| `routes/+page.svelte` | Replace: all ~15 direct mutations → helpers |

## Order of operations

1. Part B first (centralize mutations) — smaller, less risky, immediately reduces coupling
2. Part A second (editor state) — bigger rewrite, but self-contained in editor.ts + 2 components

## Risks

- Part B is mechanical search-and-replace — low risk
- Part A changes the store shape, which affects every component that subscribes to editor stores. Need to verify that Svelte's derived stores update correctly with the new shape (they will, but test it)
- The diff state (`diffBase`, `diffTarget`, etc.) should NOT be folded into `editorState` — it's display-only and has different lifecycle
