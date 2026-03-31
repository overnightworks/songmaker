# Mobile UX Pass + Design Token Centralization

## Phase 1: Design Tokens in app.css ✅ DONE

## Phase 2: Mobile List Density ✅ DONE

## Phase 3: Simplify Navigation — Actions and Gens Out of Sidebar

**Principle:** The sidebar is for navigating (Album → Song). Actions and
generation browsing live in the detail panel.

### What changes

**Sidebar becomes a clean two-level tree:**
```
▸ AAA                    2
    Bbb                  2 gens
    Ccc                  1 gen
▸ APOLOGIEZ              2
    Sunny Side Up        1 gen
```

No buttons, no gen rows, no version labels, no expand toggles for gens.

**Detail panel gains:**
- Album overview (when album selected, no song open): title, stats, Share/Clean Up/Delete
- Song view (when song selected): editor + GenerationsList (already exists)
- Gen detail (when gen selected from GenerationsList): existing GenerationDetail + delete button

### 3a. Strip sidebar to Album → Song only

**SongNode.svelte:**
- Remove gen-list, version labels, gen rows, expand toggle, gen play button
- Remove gen delete confirm, move button, show-all button
- Keep: song title, gen count badge, click to select song
- The component becomes much simpler — just a clickable row

**AlbumNode.svelte:**
- Remove SHARE, CLEAN UP, DELETE buttons
- Keep: album title, song count, expand/collapse chevron

### 3b. Album overview in detail panel

**+page.svelte:**
- When `selectedAlbumId && !selectedSongId` → show album overview
- Content: album title, artist, song count, gen count
- Actions: Share, Clean Up, Delete Album (moved from AlbumNode)
- Reuse existing API calls / handlers

### 3c. Generation delete in detail view

**GenerationDetail.svelte:**
- Add delete button at the bottom (destructive action, separated from pick/score)
- Confirmation step before delete
- On confirm: call API, update songList store, close detail

### 3d. SongNode click behavior

Currently clicking a song expands it to show gens. New behavior:
- Clicking a song selects it → detail panel shows song editor + GenerationsList
- No expand/collapse in sidebar — the song row is a flat link
- GenerationsList in the detail panel handles gen browsing

### Files to change

| File | Change |
|---|---|
| `SongNode.svelte` | Strip to flat song row (title + gen count) |
| `AlbumNode.svelte` | Remove action buttons |
| `+page.svelte` | Add album overview panel, adjust song selection flow |
| `GenerationDetail.svelte` | Add delete button with confirmation |

### What NOT to change

- GenerationsList.svelte — already shows gens in detail view, no changes needed
- Player bar — prev/next gen buttons still cycle gens, unaffected
- API layer — no changes
- Settings pages — no changes

## Phase 4: Mobile Layout (future, separate task)

- Song editor: full-screen sheet on mobile
- Claude Chat: full-screen overlay on mobile

## Execution order

1. ~~Phase 1~~ ✅
2. ~~Phase 2~~ ✅
3. Phase 3a (strip SongNode + AlbumNode) + 3b (album overview) + 3c (gen delete) — one pass
4. Phase 4 — separate task
