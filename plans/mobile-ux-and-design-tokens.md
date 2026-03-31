# Mobile UX Pass + Design Token Centralization

## Phase 1: Design Tokens in app.css ✅ DONE

## Phase 2: Mobile List Density ✅ DONE

## Phase 3: Unified Detail Panel — Album / Song / Generation

**Principle:** The sidebar is purely for navigation. The detail panel shows
context and actions for whatever is selected. Every level (album, song,
generation) follows the same pattern: header + tabs.

### Navigation model

```
Sidebar (tree)              Detail panel (tabs)
─────────────               ────────────────────
▸ AAA            2          Album: AAA
  Bbb        2 gens        Artist · 5 songs · 12 gens
  Ccc        1 gen         [Songs]  [Share]  [Manage]
▸ APOLOGIEZ      2
```

- Click album in sidebar → album detail (Songs tab)
- Click song in sidebar OR in album's Songs tab → song detail (Generations tab)
- Click generation in Generations tab → generation detail
- ← back button goes up one level

### 3a. Album detail view

When an album is selected but no song is open, the detail panel shows:

**Header:**
```
ALBUM TITLE                              [Play Album]
Artist · N songs · M generations
```

**Tabs:**
- **Songs** (default): list of songs in this album — click one to drill into song detail
- **Share**: sharing toggle, copy link button, share URL display
- **Manage**: Clean Up (delete unpicked), Delete Album — with confirmation steps

### 3b. Song detail view (existing — minimal changes)

Already works:
```
SONG TITLE                    [Save] / [Generate ×N]
Album · Artist
[Generations]  [Edit]  [Co-Writer]
```

**Changes:**
- Add ← back button that returns to album detail (currently goes to empty state)
- Future: add Share tab when song sharing is implemented

### 3c. Generation detail view (existing — minimal changes)

Already works:
```
← All generations
Generation 2  seed:4114085939
[Pick]  [Score]  [Delete]
```

No changes needed. Already has back button to song's generation list.

### 3d. Sidebar

Pure navigation tree, no buttons:
```
▸ ALBUM TITLE          N
    Song One       M gens
    Song Two       K gens
```

- Album row: click to select album + expand, chevron to toggle expand/collapse
- Song row: click to select song (opens song detail)
- No play buttons, no action buttons, no ⋯ menus

### 3e. Files to change

| File | Change |
|---|---|
| `AlbumNode.svelte` | Add onselect callback, remove play button |
| `SongList.svelte` | Pass onselect to AlbumNode |
| `+page.svelte` | Album detail with tabs (Songs/Share/Manage), back navigation from song to album |
| `navigation.ts` | Add selectAlbum function, back-to-album logic |

### 3f. What stays the same

- Song detail panel (Generations/Edit/Co-Writer tabs) — no changes
- GenerationDetail — already has delete, pick, score
- GenerationsList — already works in song detail
- Player bar — prev/next buttons cycle gens, unaffected
- API layer — no changes needed

### 3g. Future extensibility

This pattern scales cleanly:
- Song sharing → add "Share" tab to song detail
- Generation sharing → add share action to generation detail
- Album settings (colors, metadata) → add tab to album detail
- Same drill-down/back pattern at every level

## Phase 4: Mobile Layout (future, separate task)

- Song editor: full-screen sheet on mobile
- Claude Chat: full-screen overlay on mobile
- Album detail tabs stack naturally on mobile (same as settings pages)

## Execution order

1. ~~Phase 1~~ ✅
2. ~~Phase 2~~ ✅
3. Phase 3d (fix AlbumNode — onselect, remove play) — small
4. Phase 3a (album detail with tabs) — main work
5. Phase 3b (back button from song to album) — small
6. Phase 4 — separate task
