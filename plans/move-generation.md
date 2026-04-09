# Move Generation Between Songs — Feature Plan

**Status:** Proposed
**Date:** 2026-04-09

> Lets the user move an existing `Generation` row from one (song, version) to another (song, version). Designed primarily for the post-recovery cleanup workflow where 99 anonymous WAVs landed in a "Recovered (April 2026)" album and need to be reassigned to their real songs/versions.

## Why this exists

After the 2026-04-08 data wipe, 99 raw WAV files were recovered via filesystem forensics but had **no metadata** (WAVs don't carry ID3-style tags in songmaker). They were imported as a "Recovered (April 2026)" album with placeholder songs `Recovered #001` through `Recovered #099`.

The user listens to each one, identifies which real song it belongs to, and needs to move the generation row to that song. The current UI has no way to do this — only `is_picked`, `is_kept`, `is_archived` mutations exist.

Without this feature the user would either:
1. Manually run SQL UPDATE statements (tedious, error-prone)
2. Delete the recovered generations and lose them
3. Live with a junk album cluttering the UI forever

None of those are acceptable.

## Scope decisions (locked with user)

1. **Move target requires an EXISTING (song, version) pair.** No "create new version" escape hatch in the move dialog. If the user wants to move a gen to a song where the right version doesn't exist yet, they must first create the version manually (using the existing version-edit UI), then move.

2. **One generation per move action.** No bulk-move in v1. User clicks one gen, picks a destination, confirms. Bulk-move is a Phase 9+ enhancement if needed.

3. **Move includes file relocation.** Audio file paths in the audiofiles volume are organized as `<user_uuid>/<gen_uuid>.{mp3,wav}`. The gen UUID doesn't change on move, so the file path doesn't need to change. **No file move on disk** — only DB row updates.

4. **`generation_number` is renumbered within the target song.** Songmaker uses `generation_number` as a per-song sequence counter. Moving a gen to a new song means the gen gets a new `generation_number = max + 1` in the target song. The old song's gens are NOT renumbered (gaps are fine).

5. **Audit log entry on every move.** `audit_log` table records `action='move_generation', resource_type='generation', resource_id=<gen_id>, detail={from_song, from_version, to_song, to_version}`.

6. **Picks and keeps are preserved on move.** A generation marked `is_picked=true` in the source song stays `is_picked=true` in the target song (but only if no other gen in the target song is already picked — see "Edge cases"). `is_kept` is always preserved.

7. **No move across users.** A gen owned by user A cannot be moved into user B's song. Ownership checked via `check_generation_access` + `check_song_access`.

## Data model — what changes

**Schema: NO changes.** All required columns already exist:
- `generations.song_id` → mutable
- `generations.version_id` → mutable
- `generations.generation_number` → mutable

No alembic migration needed.

**Implications for existing code:**
- Currently `generation_number` is treated as set-once at insert. The move logic must allow re-numbering an existing row.
- The `is_picked` constraint ("only one picked per song") needs to be re-evaluated on the destination song when moving a picked gen in.

## API design

### New endpoint

```
POST /api/generations/{gen_id}/move
Body: {
    target_song_id: str,    # required — must be a song the user owns
    target_version_id: str, # required — must belong to target_song_id
}
Response 200: {
    generation: GenerationResponse,  # the updated row
    new_generation_number: int,
}
Response 400: { error: "..." }
Response 403: { error: "Forbidden" }
Response 404: { error: "Not found" }
Response 409: { error: "Version does not belong to target song" }
```

**Validation order in the endpoint:**
1. `check_generation_access(session, gen_id, user)` → 404 if missing, 403 if not user's
2. Load target song, check `check_song_access` → same
3. Load target version, verify `version.song_id == target_song_id` → 409 if mismatch
4. Verify the move actually changes something (target != current) → 400 "no-op"
5. Atomically: update gen row + `commit()` + audit log
6. Return updated gen

**Why a dedicated endpoint and not a generic `PATCH /generations/{id}`:**
- Move is a multi-field atomic operation with specific validation rules
- A generic PATCH would invite "update mp3_path", "update seed", etc. — none of which we want exposed
- A dedicated endpoint is auditable and discoverable

### Existing endpoints — no changes

The existing `GET /generations/{id}` returns the moved gen with its new song_id/version_id. Frontend will get the fresh state on refresh. No need to touch other endpoints.

## Backend implementation

### `db/queries/generations.py` — new function

```python
def move_generation(
    session: Session,
    generation_id: str,
    target_song_id: str,
    target_version_id: str,
) -> Generation:
    gen = session.query(Generation).filter_by(id=generation_id).first()
    if not gen:
        raise ValueError("Generation not found")

    target_version = session.query(Version).filter_by(id=target_version_id).first()
    if not target_version:
        raise ValueError("Target version not found")
    if target_version.song_id != target_song_id:
        raise ValueError("Version does not belong to target song")

    if gen.song_id == target_song_id and gen.version_id == target_version_id:
        return gen  # no-op

    # Compute new generation_number in target song
    max_num = session.query(func.coalesce(func.max(Generation.generation_number), 0)) \
        .filter(Generation.song_id == target_song_id).scalar()

    # Pick conflict resolution: if moving a picked gen into a song that already
    # has a picked gen, the moved gen loses its pick (target song's pick wins)
    if gen.is_picked:
        existing_picked = session.query(Generation).filter(
            Generation.song_id == target_song_id,
            Generation.is_picked == True,
            Generation.id != gen.id,
        ).first()
        if existing_picked:
            gen.is_picked = False

    gen.song_id = target_song_id
    gen.version_id = target_version_id
    gen.generation_number = max_num + 1
    session.flush()
    return gen
```

**Notes:**
- Uses `flush()`, not `commit()`. The endpoint commits.
- Conflict resolution for `is_picked`: target song wins. The user can re-pick after the move if they prefer the moved gen.
- `is_kept` is always preserved.

### `generation_api.py` — new endpoint

```python
class MoveGenerationRequest(BaseModel):
    target_song_id: str
    target_version_id: str

@router.post("/generations/{gen_id}/move")
def api_move_generation(
    gen_id: str,
    req: MoveGenerationRequest,
    session: Session = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> GenerationResponse:
    gen = check_generation_access(session, gen_id, user)
    target_song = check_song_access(session, req.target_song_id, user)
    if not target_song:
        raise HTTPException(404, "Target song not found")

    try:
        moved = move_generation(session, gen_id, req.target_song_id, req.target_version_id)
    except ValueError as e:
        raise HTTPException(409, str(e))

    record_audit(session, user.id, "move_generation", "generation", gen_id, detail={
        "from_song_id": gen.song_id,
        "from_version_id": gen.version_id,
        "to_song_id": req.target_song_id,
        "to_version_id": req.target_version_id,
    })
    session.commit()
    return GenerationResponse.from_orm(moved)
```

**Pattern adherence (per CLAUDE.md):**
- Endpoint commits (queries flush)
- Ownership checked via `check_generation_access` + `check_song_access` for BOTH source and target
- Pydantic request model, not raw dict
- `from_orm` on response

### `api_models.py` — new request type

```python
class MoveGenerationRequest(BaseModel):
    target_song_id: str
    target_version_id: str
```

That's the only addition. The response is the existing `GenerationResponse`.

### `audit_log` detail field

The `audit_log.detail` column is JSON. The detail dict above (from/to song/version) is small and indexable for future "show me where I moved this from" features.

### Concurrency / transaction safety

Single-row update wrapped in a single transaction. No race conditions of concern. The `is_picked` re-check is inside the same transaction so the "two picks" race is impossible.

## Frontend implementation

### New component: `MoveGenerationDialog.svelte`

Lives at `frontend/src/lib/components/MoveGenerationDialog.svelte`. Modal dialog with:

```
┌─ Move generation ─────────────────────────────────┐
│                                                    │
│  Generation #5 of "Recovered #001 (180s)"         │
│  Audio: 180s WAV                                   │
│                                                    │
│  Target album:  [Wake Up               ▾]         │
│  Target song:   [This Summer           ▾]         │
│  Target version: [v3 — "[verse] Contacts s..." ▾]│
│                                                    │
│           [Cancel]    [Move generation]            │
└────────────────────────────────────────────────────┘
```

**State machine:**
1. Album dropdown — populated from `GET /api/albums` (existing)
2. Song dropdown — filtered by selected album, populated from `GET /api/albums/{id}/songs` (existing)
3. Version dropdown — filtered by selected song, populated from `GET /api/songs/{id}/versions` (existing)
4. Each version shows `v{number} — "{first 50 chars of lyrics}"`
5. Move button is disabled until all three are selected AND the target differs from the current
6. Click → `POST /api/generations/{id}/move` → on success, close dialog, emit event to refresh the parent view

### Where the "Move" button lives

In the existing generation card UI (in `GenerationView.svelte` or wherever the gen is displayed). New button next to the existing pick/keep/delete buttons:

```
[♥ Pick]  [⭐ Keep]  [→ Move]  [🗑 Delete]
```

Clicking opens the modal.

### New API client function

```typescript
// frontend/src/lib/api/generations.ts (or wherever)
export async function moveGeneration(
    genId: string,
    targetSongId: string,
    targetVersionId: string,
): Promise<Generation> {
    const res = await fetch(`/api/generations/${genId}/move`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_song_id: targetSongId, target_version_id: targetVersionId }),
    });
    if (!res.ok) throw await apiError(res);
    return res.json();
}
```

### Type generation

After the new Pydantic request model lands in `api_models/`, run `python scripts/generate_types.py` to regenerate `frontend/src/lib/api/types.ts`.

## Tests

### Backend (`tests/test_generation_api.py` or new `test_move_generation.py`)

1. **Happy path** — move gen from song A v1 to song B v3, verify new song_id, version_id, generation_number
2. **No-op** — move to same (song, version) → returns 400 or 200 with no change
3. **Cross-user denial** — user A tries to move user B's gen → 403
4. **Cross-user target denial** — user A moves their own gen into user B's song → 403
5. **Version belongs to wrong song** — move with target_song=X, target_version=Y where Y belongs to song Z → 409
6. **Pick conflict** — moving a picked gen into a song with another picked gen, the moved gen becomes unpicked
7. **Keep preserved** — moving a kept gen, `is_kept` stays true
8. **Generation number re-assigned** — moving into a song with existing gens 1-5, the moved gen becomes #6
9. **Source song's other gens are NOT renumbered** — if moving gen #3 out of a song with gens 1-5, the remaining are 1, 2, 4, 5 (gap is fine)
10. **Audit log written** — verify the audit row exists with the right detail

### Backend (`tests/test_generations_query.py`)

1. `move_generation` query function unit tests, similar to above but at the query layer

### Frontend (`MoveGenerationDialog.test.ts`)

1. Renders with all three dropdowns
2. Move button disabled until all three selected
3. Move button disabled when target == current
4. Clicking move calls the API + closes dialog on success
5. API error displays an error message in the dialog (doesn't close)

### Frontend (`generations.test.ts` API client)

1. `moveGeneration` POST shape test

## Edge cases + decisions

### What if the move's target version was recently deleted?

Validation step 3 (`target_version.song_id == target_song_id`) handles this — if the version row no longer exists, we return 404. The dialog shows a generic error and the user reloads.

### What if the source song becomes empty after the move?

That's fine. Empty songs already exist in the schema. The user can delete the song manually.

### What if the source song was the "Recovered (April 2026)" placeholder?

Same — empty placeholder song stays around. After moving all 99 gens out, the user can delete the entire Recovered album in one click via existing delete-album functionality.

### What about file system?

**Nothing happens on disk.** The audio file is named after the gen UUID (which doesn't change), so the path stays the same. The volume's directory structure doesn't reflect album/song/version hierarchy at all — it's flat `<user_uuid>/<gen_uuid>.{mp3,wav}`.

### What about scoring?

`scores` table joins via `generation_id`. Moving the gen doesn't break the FK. Scores stay attached. **No impact.**

### What about whisper transcripts?

`generations.whisper_text` is on the gen row itself. Moves with the gen. **No impact.**

### What about co-writer chat references to generations?

`chat_messages` doesn't reference generation_id. **No impact.**

### What about playlists?

`playlist_entries.generation_id` joins to the gen. Move doesn't break the FK — the gen still exists with the same ID. The playlist entry continues to work. **No impact.**

### What if the user moves the SAME gen twice in quick succession?

Each move is a separate transaction. The second move sees the already-moved state. No race.

## Files Touched

| File | Change | Lines |
|---|---|---|
| `src/songmaker_cli/db/queries/generations.py` | Add `move_generation()` function | ~30 |
| `src/songmaker_cli/db/queries/__init__.py` | Re-export `move_generation` | 1 |
| `src/songmaker_cli/api_models/__init__.py` (or whichever holds gen models) | Add `MoveGenerationRequest` | ~5 |
| `src/songmaker_cli/generation_api.py` | Add `POST /generations/{id}/move` endpoint | ~25 |
| `tests/test_generation_api.py` | 10 new tests | ~150 |
| `tests/test_generations_query.py` | Query-level tests | ~50 |
| `frontend/src/lib/api/generations.ts` (or `client.ts`) | Add `moveGeneration` function | ~15 |
| `frontend/src/lib/api/types.ts` | REGENERATED from Pydantic models (don't edit by hand) | (auto) |
| `frontend/src/lib/components/MoveGenerationDialog.svelte` | NEW dialog component | ~150 |
| `frontend/src/lib/components/GenerationCard.svelte` (or wherever gen actions live) | Add Move button + dialog open handler | ~10 |
| `frontend/src/lib/components/MoveGenerationDialog.test.ts` | Frontend tests | ~80 |

**Not touched (per "scope discipline"):**
- `db/models.py` — no schema change
- alembic migrations — none needed
- worker code — none affected
- audio file storage — none affected
- existing endpoints — none modified

## Implementation order

1. **Backend query function** — `move_generation` in `generations.py`
2. **Query unit tests** — pass
3. **API endpoint** — `POST /generations/{id}/move`
4. **API integration tests** — pass
5. **Run `python scripts/generate_types.py`** — regenerate `types.ts`
6. **Frontend API client function** — `moveGeneration`
7. **Move dialog component** — `MoveGenerationDialog.svelte`
8. **Mount the dialog** — add Move button + handler in the gen card
9. **Frontend tests** — pass
10. **Manual smoke test** — open the UI, move a Recovered #001 to a real song, verify it appears in the target

## Smoke test plan (manual after implementation)

1. Hard refresh the UI
2. Navigate to `Recovered (April 2026)` → `Recovered #001 (180s)`
3. Click the gen → Move button → dialog opens
4. Pick album: Wake Up → song: Sleepwalking → version: v1
5. Click Move → dialog closes, gen disappears from Recovered #001
6. Navigate to Wake Up → Sleepwalking → verify the gen is now there as gen #(N+1)
7. Verify audio still plays (file path unchanged)
8. Navigate to Recovered #001 → confirm it's now empty (0 generations)
9. Repeat for a 240s WAV → Burning Through (testing the duration-based hint)
10. Try the failure paths:
    - Move to a song where target version doesn't exist (manually craft via dev tools) → expect 409
    - Move to another user's song → expect 403

## Estimated time

- Backend (query + endpoint + tests): ~1 hour
- Frontend (API client + dialog + tests): ~1.5 hours
- Smoke test + bugfix loop: ~30 min
- **Total: ~3 hours**

## Out of scope (deferred)

- **Bulk move** — moving N gens to the same target in one action. Useful if the user identifies 5 versions of "This Summer" at once and wants to move them all. Easy follow-up — just take a list of gen_ids in the request body.
- **"Create new version on the fly" in the move dialog** — explicitly rejected per user. Forces clean version structure.
- **Move with file rename on disk** — unnecessary because filenames are gen UUIDs.
- **Move history / undo** — audit log is enough. Undo would require a "move back" UI button which is a separate small feature.
- **Cross-user move (admin only)** — none of the songmaker workflows need this.

## What I need from the user before implementing

- Confirm the version dropdown should show **v{number} — first 50 chars of lyrics** as the label, OR something different (e.g., just `v{number}` is fine if lyrics are too noisy)
- Confirm the Move button placement in the gen card UI is OK (between Keep and Delete) — or somewhere else
- Confirm the pick-conflict resolution (target song's pick wins) is the right semantic
- Approve the file list above

## Questions answered after the user confirms scope

- Whether to add a "delete source song if empty after move" auto-cleanup → leaning **no**, user does it manually
- Whether to show a toast notification on successful move → **yes**, matches existing patterns
- Whether to allow moving an `is_archived` gen → **yes**, no reason to block

## What if version_id is NULL (legacy generations)?

Some pre-Phase-X generations may have `version_id = NULL` (the column was nullable historically). The move endpoint should still work — `target_version_id` is required (must exist), and the move sets it to a real value. **Moving a NULL-version gen is actually a fix**, not a regression.

The reverse (moving a gen TO a NULL version) is forbidden — the request schema requires `target_version_id`.

## Done criteria

- All 10 backend tests pass
- All 5 frontend tests pass
- Manual smoke test (steps 1-10) passes
- A user can move all 99 Recovered WAVs into their real songs in under 30 minutes total UI time
- After all moves, the Recovered album has 0 songs and can be deleted via the existing delete-album button
- Audit log contains a row for every move with from/to detail

---

**Author:** Claude (autonomous night shift, 2026-04-08 ~02:30)
**For review by:** Felix (tomorrow morning)
**Status:** Plan only. No code written yet. Awaiting approval.
