# Playlists + Smart Sections + Kept Generations

## Overview

Add playlists as a first-class entity, a "Shared" section in the sidebar, and
an `is_kept` flag on generations for cleanup protection.

Playlists contain **generation entries** — each entry points to a specific
generation (a concrete audio file). Multiple generations of the same song are
allowed in a playlist.

The Shared section is a client-side derived store over existing data. No
abstraction layer — when a second smart section is needed, generalize then.

## Design Decisions

- **Playlist entries point to generations**, not songs. A generation is a
  concrete audio file — that's what you listen to.
- **Multiple gens of the same song** are allowed in a playlist.
- **`is_kept` flag on Generation** — marks a generation as worth keeping.
  Cleanup deletes non-picked, non-kept generations. `is_kept` is set
  automatically when a gen is added to a playlist or shared. It is **sticky**:
  removing from a playlist or unsharing does NOT auto-unset it. Only manual
  un-starring clears it.
- **"Add album/song to playlist"** is a snapshot — adds current picked gens at
  that moment. Not a live link.
- **No separate "favorites" system** — playlists cover that use case.
- **Smart sections**: no `SmartFilter` abstraction. The Shared section is a
  plain derived store. Generalize when a second filter appears.
- **Deletion**: `ON DELETE CASCADE` on `PlaylistEntry.generation_id`. Deleting
  a generation removes it from all playlists.

## Target Sidebar Layout

```
Search...                              [+]
──────────────────────────────────────────
▸ SHARED                               3
    🔗 AAA                        album
    🔗 Bbb                         song
    🔗 Gen #2 — Bbb                 gen

▸ PLAYLISTS                            2
    Chill Mix                         12
    Best Of March                      5

▸ AAA                                  2
    Bbb                          2 gens
    Ccc                          1 gen
▸ APOLOGIEZ                            2
```

---

## Phase 0: `is_kept` Flag

### 0a. Migration + model

**File:** `db/models.py`

Add to `Generation`:

```python
is_kept: Mapped[bool] = mapped_column(Boolean, default=False)
```

Alembic migration: add `is_kept` column to `generations` table.

### 0b. Update cleanup logic

**File:** `db/queries/albums.py`

`cleanup_album()` currently skips `is_picked` generations. Update to also skip
`is_kept`:

```python
# delete where NOT is_picked AND NOT is_kept
```

### 0c. Auto-set `is_kept` on share

**File:** `db/queries/generations.py`

`enable_generation_sharing()` sets `is_kept = True` on the generation.

**File:** `db/queries/songs.py`

`enable_song_sharing()` sets `is_kept = True` on the picked generation.

### 0d. UI — star/keep toggle on generations

Add a star/pin icon to each generation in the song detail view. Clicking
toggles `is_kept`. Visually distinguish kept gens (filled star vs outline).

### 0e. API endpoint

- `PATCH /api/generations/{id}/keep` — toggle `is_kept`

### 0f. Tests

- Cleanup skips kept generations
- Sharing auto-sets `is_kept`
- Toggle endpoint works
- Kept + picked both survive cleanup

---

## Phase 1: Playlists — Backend

### 1a. DB models

**File:** `db/models.py`

```python
class Playlist(Base):
    __tablename__ = "playlists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    share_slug: Mapped[str | None] = mapped_column(
        String(36), unique=True, nullable=True, index=True,
    )
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow, onupdate=_utcnow)

    entries: Mapped[list[PlaylistEntry]] = relationship(
        back_populates="playlist", cascade="all, delete-orphan",
        order_by="PlaylistEntry.position",
    )


class PlaylistEntry(Base):
    __tablename__ = "playlist_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    playlist_id: Mapped[str] = mapped_column(ForeignKey("playlists.id"), index=True)
    generation_id: Mapped[str] = mapped_column(
        ForeignKey("generations.id", ondelete="CASCADE"), index=True,
    )
    position: Mapped[int] = mapped_column(Integer)
    added_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)

    playlist: Mapped[Playlist] = relationship(back_populates="entries")
    generation: Mapped[Generation] = relationship()
```

### 1b. Alembic migration

New `playlists` and `playlist_entries` tables.

### 1c. DB queries

**New file:** `db/queries/playlists.py`

- `list_playlists(session, user_id)` → all playlists for user
- `get_playlist(session, playlist_id)` → with entries + generation + song loaded
- `create_playlist(session, title, user_id)` → new empty playlist
- `delete_playlist(session, playlist_id)` → cascade deletes entries
- `update_playlist(session, playlist_id, title)` → rename
- `add_generation_to_playlist(session, playlist_id, generation_id, position=None)`
  → append or insert at position, auto-sets `is_kept = True` on the generation
- `add_song_to_playlist(session, playlist_id, song_id)` → adds picked gen,
  auto-sets `is_kept = True`
- `add_album_to_playlist(session, playlist_id, album_id)` → snapshot: adds all
  picked gens from all songs, auto-sets `is_kept = True` on each
- `remove_from_playlist(session, playlist_id, entry_id)`
- `reorder_playlist_entry(session, playlist_id, entry_id, new_position)` →
  moves one entry, backend reindexes surrounding positions
- `get_playlist_by_slug(session, slug)` → public share lookup
- `enable_playlist_sharing(session, playlist_id)` / `disable_playlist_sharing`

Re-export from `db/queries/__init__.py`.

### 1d. API models

**New file:** `api_models/playlists.py`

```python
class PlaylistResponse(BaseModel):
    id: str
    title: str
    entry_count: int
    is_shared: bool = False
    share_slug: str | None = None
    created_at: str | None = None

class PlaylistDetailResponse(PlaylistResponse):
    entries: list[PlaylistEntryResponse]

class PlaylistEntryResponse(BaseModel):
    id: str
    position: int
    generation_id: str
    song_title: str
    album_title: str
    artist: str
    generation_number: int
    mp3_path: str
    seed: int | None

class PlaylistCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)

class AddGenerationToPlaylistRequest(BaseModel):
    generation_id: str

class AddSongToPlaylistRequest(BaseModel):
    song_id: str

class AddAlbumToPlaylistRequest(BaseModel):
    album_id: str

class SharedPlaylistResponse(BaseModel):
    title: str
    entries: list[SharedPlaylistEntry]

class SharedPlaylistEntry(BaseModel):
    song_title: str
    artist: str
    generation_number: int
    audio_url: str | None
```

### 1e. API endpoints

**New file:** `playlist_api.py`

- `GET /api/playlists` → list user's playlists
- `POST /api/playlists` → create playlist
- `GET /api/playlists/{id}` → get playlist with entries
- `PUT /api/playlists/{id}` → rename
- `DELETE /api/playlists/{id}` → delete playlist
- `POST /api/playlists/{id}/entries/generation` → add generation
- `POST /api/playlists/{id}/entries/song` → add picked gen of song
- `POST /api/playlists/{id}/entries/album` → add all picked gens of album
- `DELETE /api/playlists/{id}/entries/{entry_id}` → remove entry
- `PATCH /api/playlists/{id}/entries/{entry_id}/position` → reorder single entry
- `POST /api/playlists/{id}/share` / `DELETE /api/playlists/{id}/share`

**File:** `sharing_api.py`

- `GET /shared/playlist/{slug}` → public playlist view
- `GET /shared/playlist/{slug}/audio/{filename}` → public audio

All endpoints use ownership checks. All public endpoints use the existing
IP-based rate limiter.

### 1f. Register router

**File:** `server.py` — add `playlist_api.router`

### 1g. Tests

- Playlist CRUD
- Add generation/song/album to playlist (verify `is_kept` auto-set)
- Remove entry, reorder entry
- Share/unshare playlist
- Public playlist share page
- Ownership checks on all endpoints
- Concurrent reorder safety (entry-level moves, not full-list replace)
- CASCADE: deleting a generation removes its playlist entries

---

## Phase 2: Playlists — Frontend

### 2a. Generate types + API client

```bash
python scripts/generate_types.py
```

**File:** `client.ts`

- `fetchPlaylists()`, `createPlaylist(title)`, `fetchPlaylist(id)`
- `deletePlaylist(id)`, `updatePlaylist(id, title)`
- `addGenerationToPlaylist(playlistId, generationId)`
- `addSongToPlaylist(playlistId, songId)`
- `addAlbumToPlaylist(playlistId, albumId)`
- `removeFromPlaylist(playlistId, entryId)`
- `reorderPlaylistEntry(playlistId, entryId, newPosition)`
- `sharePlaylist(id)` / `unsharePlaylist(id)`

### 2b. Playlist store

**New file:** `stores/playlists.ts`

- `playlistList` writable store (like `albumList`)
- `selectedPlaylistId` writable store
- `selectedPlaylist` derived (detail when selected)
- Loaded alongside albums/songs on mount in `+page.svelte`

### 2c. SongList — add Playlists section

**File:** `SongList.svelte`

Add a collapsible "PLAYLISTS" group above the album tree. Each playlist
is a clickable row showing title + entry count. Clicking opens the playlist
detail in the main panel. Selected playlist gets the accent highlight.

### 2d. Playlist detail panel

**File:** `+page.svelte`

New `{:else if selectedPlaylist}` branch (same pattern as album detail):
- Header: title + Play + Share + overflow (Rename, Delete)
- Content: ordered list of entries — song title, artist, gen number, play
  button
- Drag-to-reorder (or up/down buttons for simplicity)

### 2e. "Add to Playlist" in overflow menus

At every level (album, song, generation), add an "Add to Playlist" item
to the OverflowMenu. Clicking opens a small dropdown showing existing
playlists + "New Playlist" at the bottom. Selecting one calls the
appropriate API endpoint.

This needs a new component: `PlaylistPicker.svelte` — a small modal/dropdown
that lists playlists and handles selection.

### 2f. Playlist navigation + player integration

- `navigation.ts`: `selectPlaylist(id)`, `deselectPlaylist()`
- Player: `playPlaylist(playlistId)` — queues all entries, plays first,
  auto-advances through the list

### 2g. Public share page

**New file:** `routes/share/playlist/[slug]/+page.svelte`

Similar to album share page — tracklist with SharedPlayer for the currently
playing entry.

### 2h. Tests

- `pnpm check && pnpm lint && pnpm test`

---

## Phase 3: Shared Section in Sidebar

### 3a. Derived store from existing data

No new API needed. Shared items are already in the album/song stores
(`is_shared` field). The shared section is a client-side derived store:

```typescript
const sharedItems = $derived([
    ...albums.filter(a => a.is_shared).map(a => ({
        id: a.id, type: 'album', label: a.title
    })),
    ...songs.filter(s => s.is_shared).map(s => ({
        id: s.id, type: 'song', label: s.title
    })),
    ...songs.flatMap(s =>
        s.generations.filter(g => g.is_shared).map(g => ({
            id: g.id, type: 'generation',
            label: `Gen #${g.generation_number} — ${s.title}`
        }))
    )
]);
```

### 3b. SongList — add Shared section above Playlists

**File:** `SongList.svelte`

New collapsible section at the top. Renders items from the derived store.
Hidden when empty (no shared items = section doesn't appear).

Clicking an item navigates to the appropriate detail view:
- Album → `selectAlbumOverview(id)`
- Song → `selectSong(id)`
- Generation → `selectSong(songId)` then `selectGeneration(gen, song)`

### 3c. Tests

- `pnpm check && pnpm lint && pnpm test`

### 3d. Future extensibility (no code now, just notes)

To add a new smart section (e.g. "High Rated"):

1. Add a new derived store that filters by the criteria
2. Add a new collapsible section to SongList that renders it
3. If patterns repeat, extract a generic `SmartSection` component + filter
   interface at that point

To add user-created filters:

1. Add `SmartSection` model to DB (id, title, filter_json, user_id)
2. API: CRUD for smart sections
3. Store: `smartSections` writable loaded on mount
4. Sidebar renders from store instead of constant
5. Filter editor UI (field + operator + value) for creating/editing

---

## Execution Order

1. Phase 0 — `is_kept` flag (migration, cleanup update, share auto-set, UI, tests)
2. Phase 1 — Playlist backend (models, migration, queries, endpoints, tests)
3. Phase 2 — Playlist frontend (types, store, sidebar, detail, picker, tests)
4. Phase 3 — Shared section (derived store, sidebar, tests)

---

## Files Changed (summary)

| File | Phase | Change |
|---|---|---|
| `db/models.py` | 0a, 1a | `is_kept` on Generation, Playlist + PlaylistEntry models |
| Migration (new) | 0a | Add `is_kept` column |
| Migration (new) | 1b | New playlist tables |
| `db/queries/albums.py` | 0b | Cleanup skips `is_kept` |
| `db/queries/generations.py` | 0c, 0e | Share auto-sets `is_kept`, toggle endpoint |
| `db/queries/songs.py` | 0c | Share auto-sets `is_kept` on picked gen |
| `db/queries/playlists.py` (new) | 1c | Playlist query functions |
| `db/queries/__init__.py` | 1c | Re-exports |
| `api_models/playlists.py` (new) | 1d | Request/response models |
| `api_models/__init__.py` | 1d | Re-exports |
| `playlist_api.py` (new) | 1e | REST endpoints |
| `generation_api.py` | 0e | Keep toggle endpoint |
| `sharing_api.py` | 1e | Public playlist share |
| `server.py` | 1f | Register router |
| `types.ts` | 2a | Generated |
| `client.ts` | 2a | Playlist API calls |
| `stores/playlists.ts` (new) | 2b | Playlist store |
| `SongList.svelte` | 2c, 3b | Playlist + Shared section groups |
| `+page.svelte` | 0d, 2d, 2e | Keep toggle, playlist detail, add-to-playlist |
| `PlaylistPicker.svelte` (new) | 2e | Playlist selection dropdown |
| `navigation.ts` | 2f | Playlist navigation |
| `stores/player.ts` | 2f | Play playlist |
| `share/playlist/[slug]/+page.svelte` (new) | 2g | Public playlist page |
