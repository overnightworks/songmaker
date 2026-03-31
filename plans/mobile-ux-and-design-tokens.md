# Mobile UX Pass + Design Token Centralization

## Phase 1: Design Tokens in app.css ✅ DONE

Design tokens added to `:root` in app.css. Mobile breakpoint overrides bump sizes
automatically. All 9 component files reference tokens instead of hardcoded values.

## Phase 2: Mobile List Density ✅ DONE

Touch targets, font sizes, and padding bumped on mobile across SongList, AlbumNode,
SongNode, GenerationsList, and the main page.

## Phase 3: Move Actions Out of the Navigation Tree

**Principle:** The sidebar is for navigating. Actions live in the detail view.

Currently, album actions (Share, Clean Up, Delete) and generation delete (X) are
inline in the sidebar tree. This causes:
- Mis-taps on mobile (navigate vs delete is a precision game)
- Visual clutter in the tree
- Inconsistency (pick/score are already in the detail view, but delete is not)

### 3a. Clean up the sidebar

**AlbumNode.svelte** — Remove SHARE, CLEAN UP, DELETE buttons from the album row.
The sidebar becomes pure navigation:

```
▸ AAA                    2
    Bbb                  2 gens
    Ccc                  1 gen
▸ APOLOGIEZ              2
```

**SongNode.svelte** — Remove the inline X (delete) button from generation rows.
Gen rows become click-to-view only:

```
  V2
    ▸ gen2         seed:4114085939
    ▸ gen1         seed:3455212430
```

### 3b. Album detail view (new)

When an album is selected but no song is opened, the detail panel shows an
album overview instead of being empty. This is the new home for album actions.

**Where:** `+page.svelte` detail panel area. Add a conditional block:
if album selected and no song selected → show album overview.

**Content:**
```
ALBUM TITLE
Artist · N songs · M generations

[Share]  [Clean Up]  [Delete Album]

Song list summary or recent activity could go here later.
```

**Implementation:**
- Add `selectedAlbumDetail` derived store (or compute inline) from
  `selectedAlbumId` + `albumList` + `songList`
- Render in the detail panel when `!selectedSong && selectedAlbumId`
- Move the share/cleanup/delete handlers from AlbumNode into this view
- The API calls stay identical — just the UI trigger moves

### 3c. Generation delete in detail view

**GenerationDetail.svelte** already shows pick and score buttons. Add a delete
button there, with a confirmation step (same pattern as the current inline confirm).

**Where:** In the gen-header or actions row of GenerationDetail.svelte.

**Content:**
```
gen2  seed:4114085939  [Pick] [Score] [Delete]
```

Or at the bottom of the detail panel as a destructive action:
```
[Delete Generation]
```

The bottom placement is better — it separates the common actions (pick, score)
from the destructive one. Matches how settings pages handle "Delete Account".

**Implementation:**
- Add delete handler to GenerationDetail (import `deleteGeneration` from API client)
- Add confirmation state (same `showConfirm` pattern used in SongNode)
- On confirm: call API, remove from songList store, close detail view
- Remove the X button from SongNode gen rows

### 3d. Files to change

| File | Change |
|---|---|
| `AlbumNode.svelte` | Remove SHARE, CLEAN UP, DELETE buttons and handlers |
| `SongNode.svelte` | Remove gen X button and delete confirm logic |
| `+page.svelte` | Add album overview in detail panel |
| `GenerationDetail.svelte` | Add delete button with confirmation |

### 3e. What NOT to change

- Song-level actions (the song detail/editor view) — already in the right place
- Player bar — already fixed
- Settings pages — already fine
- The API layer — no changes needed

## Phase 4: Mobile Layout (future, separate task)

### Song editor on mobile
- Right panel is cramped on mobile
- Consider: full-screen sheet/modal for editing
- Claude Chat: same treatment — full screen overlay

### Navigation
- Settings pages stack naturally — no changes needed
- Main tree view is clean after Phase 3 simplification

## Execution order

1. ~~Phase 1 (design tokens)~~ ✅
2. ~~Phase 2 (mobile density)~~ ✅
3. Phase 3a + 3b (clean sidebar + album overview) — do together
4. Phase 3c + 3d (gen delete in detail) — do together
5. Phase 4 (mobile layout) — separate task, lower priority
