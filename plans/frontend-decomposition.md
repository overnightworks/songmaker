# Frontend Component Decomposition

> **Status: PHASE 1+2 DONE** — SongList split into AlbumNode + SongNode, CreateForm extracted from +page.svelte. Phase 3 (ClaudeChat) deferred — diminishing returns.

## Problem

Three oversized components make the frontend hard to modify and impossible to test at the component level:

| Component | Lines | Responsibilities |
|-----------|-------|-----------------|
| `+page.svelte` | 658 | Album/song creation, generation triggers, scoring, tab switching, keybindings, layout orchestration |
| `SongList.svelte` | 923 | Album display, song display, generation display, playback controls, sharing, deletion, song movement, search, confirmation dialogs |
| `ClaudeChat.svelte` | 772 | Chat history, @song mentions, scope toggle, localStorage persistence, songmaker block parsing, apply/diff flow |

10 stores with implicit derived dependencies create a state interaction graph that's hard to reason about without reading 4+ files.

## Goal

Each component under 300 lines. Clear parent-child data flow. A contributor can modify one feature without understanding the full state graph.

## Phase 1: Extract from `SongList.svelte` (923 → ~200 + 4 children)

Split the tree into composable nodes:

```
SongList.svelte (~200 lines — container, search, album list)
├── AlbumNode.svelte (~150 lines — album header, sharing, delete, create song)
│   └── SongNode.svelte (~150 lines — song row, expand/collapse, move)
│       └── GenerationNode.svelte (~100 lines — generation row, playback, pick badge)
└── ConfirmDialog.svelte (~50 lines — reusable confirmation modal)
```

### File ownership
- `SongList.svelte` — search bar, album iteration, "new album" button
- `AlbumNode.svelte` — album header, share/unshare, delete album, song count
- `SongNode.svelte` — song row, expand to show generations, move-to-album dropdown
- `GenerationNode.svelte` — generation row, play button, pick/score badges
- `ConfirmDialog.svelte` — generic confirm/cancel dialog (used by album delete, generation delete)

### Data flow
- `SongList` passes album data down as props
- Each node emits events up (on:select, on:play, on:delete)
- No direct store imports in leaf nodes — parent wires stores to events

## Phase 2: Extract from `+page.svelte` (658 → ~200 + 3 children)

```
+page.svelte (~200 lines — layout shell, routing, store wiring)
├── CreateSongForm.svelte (~100 lines — new song + album creation)
├── GenerationControls.svelte (~80 lines — generate button, count selector, job status)
└── KeyboardHandler.svelte (~50 lines — keyboard shortcuts, extracted from inline handlers)
```

### Data flow
- `+page.svelte` owns the layout grid (sidebar + detail panel)
- Creation forms emit events, page handles API calls + store updates
- `GenerationControls` reads from `activeJobs` store, emits generate/score events

## Phase 3: Extract from `ClaudeChat.svelte` (772 → ~250 + 2 children)

```
ClaudeChat.svelte (~250 lines — chat container, message list, input)
├── ChatMessage.svelte (~100 lines — single message rendering, songmaker block detection)
└── SongMention.svelte (~50 lines — @song autocomplete popup)
```

### Data flow
- Chat history stays in `ClaudeChat` (localStorage-backed, scoped by song/album)
- `ChatMessage` is a pure display component
- `SongMention` emits selected song, parent inserts into input

## Phase 4: State interaction diagram

Create `docs/frontend-state.md` documenting:

```
User clicks song in sidebar
  → SongNode emits on:select
  → SongList calls selectSong() [navigation store]
    → navigation store updates selectedSongId
    → player store derives selectedSong
    → +page.svelte $effect triggers loadSongData() [editor store]
    → +page.svelte $effect triggers ensureGenerationsLoaded() [player store]
```

Document the 5 most common user flows this way. This is the missing "how does it all fit together" document.

## Constraints

- No store API changes in Phase 1-3 — components change, stores stay stable
- Each phase is independently shippable and testable
- Existing frontend tests (stores, utils, client) must keep passing after each phase
- New components get basic smoke tests with `@testing-library/svelte` (render, key interactions)

## Order

Phase 1 first — `SongList` is the most complex and touches the most code paths. Phase 4 (diagram) can happen in parallel with any phase. Phases 2 and 3 are independent of each other.

## Estimated effort

- Phase 1: ~3 hours (mechanical extraction, no logic changes)
- Phase 2: ~2 hours
- Phase 3: ~2 hours
- Phase 4: ~1 hour
