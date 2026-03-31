# UI Redesign: Actions-Not-Tabs + Universal Sharing

## Problem

The album detail view uses tabs (Songs / Share / Manage) but Share and Manage
are action panels, not content views. Songs is the only real content. This
creates an inconsistency — generation-level actions (Play, Pick, Score, Delete)
are just buttons, but album-level actions (Share, Clean Up, Delete) are hidden
behind tab navigation. The pattern doesn't scale: adding Share to songs or
generations would mean more fake tabs.

Mobile album view is also broken — `selectAlbumOverview` doesn't properly
trigger the detail panel visibility on mobile.

## Design Principles

1. **Actions are buttons, not tabs.** Tabs are for switching between content views.
2. **Every level follows the same layout:** Header (title + actions) → Content.
3. **Share is a universal action** available at album, song, and generation level.
4. **Overflow menu (`...`)** collects destructive/secondary actions at every level.

## Target Layout

### Album Detail
```
AAA                                    [▶ Play]  [↗ Share]  [⋯]
2 songs · 3 generations                              ⋯ → Clean Up | Delete

  Bbb                                           2 gens
  Ccc                                           1 gen
```
No tabs. Song list IS the content.

### Song Detail
```
← AAA
BBB                                    [Generate ×1]  [↗ Share]  [⋯]
[Generations]  [Edit]  [Co-Writer]                        ⋯ → Delete
```
Tabs stay — three genuinely different content views. Share is a header button.

### Generation Detail
```
← All generations
GENERATION 2    ☆ Pick for Album       [↗ Share]  [⋯]
v2 · seed:4114085939                          ⋯ → Re-Score | Delete
```
Share button + overflow for secondary actions.

---

## Phase 1: Frontend Restructure (no backend changes)

Refactor the album detail UI and fix mobile. No new features — just clean up
the existing layout to match the new pattern.

### 1a. OverflowMenu component
**New file:** `frontend/src/lib/components/OverflowMenu.svelte`

Reusable `⋯` button that opens a dropdown with action items. Props:
- `items: Array<{ label: string, onclick: () => void, destructive?: boolean }>`
- Closes on click-outside or item selection
- Destructive items render in red

### 1b. Album detail — remove tabs
**File:** `frontend/src/routes/+page.svelte` (album detail section, ~lines 414-526)

- Remove the `albumTab` tab bar and tab content switching
- Show song list directly (was the Songs tab content)
- Move Share toggle to a header button (reuse existing share/unshare logic)
- Move Clean Up and Delete to an OverflowMenu
- Keep Play Album as primary CTA

**File:** `frontend/src/lib/stores/navigation.ts`
- Remove `albumTab` store (no longer needed)

### 1c. Song detail — add overflow menu + delete song backend
**File:** `frontend/src/routes/+page.svelte` (song detail section, ~lines 287-412)

- Add OverflowMenu with "Delete Song"
- No other changes — tabs stay

**Backend — delete song endpoint (currently missing):**

**File:** `src/songmaker_cli/db/queries/songs.py`
- `delete_song(session, song_id)` → deletes the song and all its generations/versions

**File:** `src/songmaker_cli/song_api.py`
- `DELETE /api/songs/{song_id}` → ownership check + delete song + commit

**File:** `frontend/src/lib/api/client.ts`
- `deleteSong(songId)` API call

### 1d. Generation detail — add overflow menu
**File:** `frontend/src/lib/components/GenerationDetail.svelte`

- Move Delete and Re-Score into an OverflowMenu
- Keep Pick as a direct button (primary action)

### 1e. Fix mobile album view
**File:** `frontend/src/routes/+page.svelte`

The issue: `selectAlbumOverview` sets the selected album but the mobile CSS
uses `.has-detail` to toggle between sidebar and detail panel. Need to verify
that selecting an album sets the right state for `.has-detail` to trigger.

Check: does `selectedAlbum` without `selectedSong` count as "has detail"?
The `has-detail` class is likely only set when a song is selected. Fix: also
set it when an album is selected.

---

## Phase 2: Song & Generation Sharing (backend + frontend)

Extend the existing album sharing pattern to songs and generations.

### 2a. DB migration — add share fields to Song and Generation
**File:** new Alembic migration

```sql
ALTER TABLE songs ADD COLUMN share_slug VARCHAR UNIQUE;
ALTER TABLE songs ADD COLUMN is_shared BOOLEAN DEFAULT FALSE NOT NULL;
ALTER TABLE generations ADD COLUMN share_slug VARCHAR UNIQUE;
ALTER TABLE generations ADD COLUMN is_shared BOOLEAN DEFAULT FALSE NOT NULL;
```

**File:** `src/songmaker_cli/db/models.py`
- Add `share_slug: Mapped[str | None]` and `is_shared: Mapped[bool]` to Song
- Add `share_slug: Mapped[str | None]` and `is_shared: Mapped[bool]` to Generation

### 2b. DB queries
**File:** `src/songmaker_cli/db/queries/songs.py`
- `enable_song_sharing(session, song_id)` → generates UUID slug, sets is_shared=True
- `disable_song_sharing(session, song_id)` → clears slug, sets is_shared=False
- `get_song_by_slug(session, slug)` → returns Song with generations loaded

**File:** `src/songmaker_cli/db/queries/generations.py` (new or existing)
- `enable_generation_sharing(session, generation_id)` → generates UUID slug
- `disable_generation_sharing(session, generation_id)` → clears slug
- `get_generation_by_slug(session, slug)` → returns Generation with song loaded

Re-export from `db/queries/__init__.py`.

### 2c. API models
**File:** `src/songmaker_cli/api_models/songs.py`
- Add `is_shared` and `share_slug` to `SongResponse` / `SongSummaryResponse`
- Add `is_shared` and `share_slug` to `GenerationResponse`
- Add `SharedSongResponse` (single song public view)
- Add `SharedGenerationResponse` (single generation public view)

### 2d. API endpoints
**File:** `src/songmaker_cli/song_api.py`
- `POST /api/songs/{song_id}/share` → enable sharing, return ShareResponse
- `DELETE /api/songs/{song_id}/share` → disable sharing

**File:** `src/songmaker_cli/generation_api.py`
- `POST /api/generations/{generation_id}/share` → enable sharing, return ShareResponse
- `DELETE /api/generations/{generation_id}/share` → disable sharing

**File:** `src/songmaker_cli/sharing_api.py`
- `GET /shared/song/{slug}` → public song view (picked generation audio)
- `GET /shared/song/{slug}/audio/{filename}` → public audio for shared song
- `GET /shared/gen/{slug}` → public generation view (single audio + metadata)
- `GET /shared/gen/{slug}/audio/{filename}` → public audio for shared generation

All public endpoints get the same IP-based rate limiting as existing album shares.

### 2e. Generate TypeScript types
```bash
python scripts/generate_types.py
```

### 2f. Frontend API client
**File:** `frontend/src/lib/api/client.ts`
- `shareSong(songId)` / `unshareSong(songId)`
- `shareGeneration(generationId)` / `unshareGeneration(generationId)`

### 2g. ShareButton component
**New file:** `frontend/src/lib/components/ShareButton.svelte`

Reusable share toggle. Props:
- `isShared: boolean`
- `shareSlug: string | null`
- `onShare: () => Promise<ShareResult>`
- `onUnshare: () => Promise<void>`

Shows share icon. When clicked:
- If not shared → calls onShare, copies link to clipboard
- If shared → shows link + copy button + unshare option

### 2h. Wire ShareButton into all detail views
- Album detail header: ShareButton for album
- Song detail header: ShareButton for song
- Generation detail header: ShareButton for generation

### 2i. Public share pages
**New file:** `frontend/src/routes/share/song/[slug]/+page.svelte`
- Single song player (title, audio, play/pause/seek)
- Similar to existing album share page but for one track

**New file:** `frontend/src/routes/share/gen/[slug]/+page.svelte`
- Single generation player (generation number, seed, scores if available, audio)

---

## Phase 3: Tests

- Backend: test share/unshare endpoints for songs and generations
- Backend: test public share pages return correct data
- Backend: test rate limiting on new public endpoints
- Backend: test access control (only owner can share)
- Frontend: `pnpm check && pnpm lint && pnpm test`

---

## Files Changed (summary)

| File | Phase | Change |
|---|---|---|
| `OverflowMenu.svelte` (new) | 1a | Reusable dropdown menu |
| `+page.svelte` | 1b-1e | Album tabs removed, overflow menus added, mobile fix |
| `navigation.ts` | 1b | Remove albumTab store |
| `db/queries/songs.py` | 1c | `delete_song()` query |
| `song_api.py` | 1c | `DELETE /api/songs/{song_id}` endpoint |
| `client.ts` | 1c | `deleteSong()` API call |
| `GenerationDetail.svelte` | 1d | Overflow menu for Delete/Re-Score |
| DB migration (new) | 2a | share_slug + is_shared on Song, Generation |
| `db/models.py` | 2a | New fields |
| `db/queries/songs.py` | 2b | Song sharing queries |
| `db/queries/generations.py` | 2b | Generation sharing queries |
| `db/queries/__init__.py` | 2b | Re-exports |
| `api_models/songs.py` | 2c | New response models |
| `song_api.py` | 2d | Share endpoints |
| `generation_api.py` | 2d | Share endpoints |
| `sharing_api.py` | 2d | Public share views |
| `types.ts` | 2e | Generated |
| `client.ts` | 2f | Share API calls |
| `ShareButton.svelte` (new) | 2g | Reusable share toggle |
| `+page.svelte` | 2h | Wire ShareButton |
| `share/song/[slug]/+page.svelte` (new) | 2i | Public song page |
| `share/gen/[slug]/+page.svelte` (new) | 2i | Public generation page |

## Execution Order

1. Phase 1a → 1b → 1c + 1d (parallel) → 1e → verify frontend works
2. Phase 2a → 2b → 2c → 2d → 2e → 2f → 2g → 2h + 2i (parallel)
3. Phase 3: tests
