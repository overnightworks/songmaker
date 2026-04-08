# Soft Delete Plan

## Goal

Albums and songs get soft delete with a 30-day undo window. Generations stay hard delete. The user must be able to "undelete" everything they removed in the last 30 days, without silently undoing earlier deletions.

## Tradeoffs (accept these explicitly)

- **Disk doubles for up to 30 days.** Soft-deleted songs keep their mp3/wav files until the cleanup job runs. Acceptable for a single-user deployment; revisit if storage becomes a constraint.
- **In-flight generations may land on a soft-deleted song.** A job running at delete time will still write a Generation row. Cleanup picks it up later. No special handling.
- **Restore window is exactly enforced by the API**, not by the cleanup job's schedule (which is fuzzy).

## Mechanism: global query filter, not manual sprinkling

Add `deleted_at: datetime | None` to `Album` and `Song`. Default `None`.

**Do not** add `.filter(... .is_(None))` to every query function. That will leak — the codebase has 10+ query entry points across `albums.py`, `songs.py`, chat mention resolution, playlist traversal, sharing, and search. Manually filtering each one guarantees missed spots.

Instead, register a SQLAlchemy `with_loader_criteria` global loader option in `db/session.py` so every query against `Album` and `Song` automatically appends `deleted_at IS NULL`, *unless* the call site opts out:

```python
session.execute(
    select(Album).execution_options(include_deleted=True)
)
```

Only three places opt out:
1. `restore_album` / `restore_song` (need to find the row to restore)
2. `cleanup_expired` (the periodic hard-delete job)
3. The admin/audit views, if any

Everything else — list, get, by-slug, mention resolution, playlist joins, sharing — gets the filter for free. This is the only safe approach; document it in `db/session.py` with a comment block.

## Cascading delete: stamp a shared timestamp

When the user soft-deletes an album, every *currently-live* song in it gets the **same** `deleted_at` timestamp as the album. Songs that were already soft-deleted (earlier, individually) are left alone.

```python
def soft_delete_album(session, album_id):
    now = utcnow()
    album = session.get(Album, album_id)  # bypass filter
    album.deleted_at = now
    for song in album.songs:
        if song.deleted_at is None:
            song.deleted_at = now
    session.flush()
```

## Cascading restore: only restore the matching group

When the user clicks Undo on the album, only restore songs whose `deleted_at == album.deleted_at`. Songs the user had killed *earlier* stay deleted.

```python
def restore_album(session, album_id):
    album = session.get(Album, album_id, include_deleted=True)
    if album.deleted_at is None:
        return album
    if utcnow() - album.deleted_at > RESTORE_WINDOW:
        raise GoneError(...)
    cascade_ts = album.deleted_at
    album.deleted_at = None
    for song in album.songs:  # opt-in to include_deleted on the relationship
        if song.deleted_at == cascade_ts:
            song.deleted_at = None
    session.flush()
```

This preserves user intent: deleting an album doesn't silently revive songs you already threw away.

`RESTORE_WINDOW` is a `Final` constant in `constants.py` (default 30 days, configurable via env).

## API endpoints

All four endpoints enforce ownership via `check_album_access` / `check_song_access` from `api_helpers.py` — same as every other resource endpoint. Never skip.

**Albums:**
- `DELETE /api/albums/{id}` — soft delete (cascades to live songs). Records `AuditAction.DELETE`.
- `POST /api/albums/{id}/restore` — clears `deleted_at` on the album and on songs sharing the cascade timestamp. Returns:
  - `200` with the restored album
  - `404` if the album doesn't exist at all
  - `410 Gone` if `now - deleted_at > RESTORE_WINDOW` (the row exists but the window has passed)
  - Records `AuditAction.RESTORE` (new enum value).

**Songs:**
- `DELETE /api/songs/{id}` — soft delete (single song only).
- `POST /api/songs/{id}/restore` — clears `deleted_at`. 404 / 410 same as above.

**`AuditAction.RESTORE`** is a new value in the audit enum. Add it.

## Boundary checks the soft-delete plan must enforce

These are the bugs that show up if you only do "filter the lists":

1. **`move_song`** — reject if source song or target album is soft-deleted. 404 / 422.
2. **Sharing endpoints** — `get_album_by_slug` / `get_song_by_slug` benefit from the global filter, so `/share/{slug}` automatically 404s on soft-deleted entities. Verify with a test.
3. **Mention resolution in chat** — uses the same query functions, so it inherits the filter. Verify with a test.
4. **Playlist entries** — `PlaylistEntry` references `Generation`, not `Song`, so the global filter does **not** cover this. Two-part fix:
   - Server-side: `list_playlist_entries` joins `Generation → Song → Album` and filters out entries whose Song or Album is soft-deleted.
   - The entries themselves are not deleted from the DB. If the user restores the song/album, they reappear automatically.
5. **`create_song` track numbering** — `max(track_number) + 1` must include soft-deleted songs in the lookup, so a restored song never collides with a newer one created in its slot.
   ```python
   max_track = session.query(Song.track_number).filter_by(album_id=album_id) \
       .execution_options(include_deleted=True) \
       .order_by(Song.track_number.desc()).first()
   ```
6. **In-flight generation jobs** — no change. A worker that completes after the song is soft-deleted will write a `Generation` row tied to a soft-deleted song. The next cleanup run sweeps it. Document this in the cleanup job comment.

## Permanent cleanup job

Periodic arq task in `jobs.py` (or new `cleanup.py`), scheduled daily.

```python
async def cleanup_expired(ctx):
    cutoff = utcnow() - RESTORE_WINDOW
    with get_db_session() as session:
        expired_albums = session.query(Album) \
            .execution_options(include_deleted=True) \
            .filter(Album.deleted_at < cutoff).all()
        expired_songs = session.query(Song) \
            .execution_options(include_deleted=True) \
            .filter(Song.deleted_at < cutoff, Song.album_id.notin_([a.id for a in expired_albums])).all()

        paths = []
        for album in expired_albums:
            paths.extend(delete_album(session, album.id))  # existing hard-delete fn
        for song in expired_songs:
            paths.extend(delete_song(session, song.id))    # existing hard-delete fn
        session.commit()

    for p in paths:
        unlink_quiet(p)
    log.info("cleanup_expired: removed %d albums, %d orphan songs",
             len(expired_albums), len(expired_songs))
```

Key points:
- **Reuses the existing `delete_album` / `delete_song`** query functions (which already collect mp3/wav paths before the ORM cascade fires). No reimplementation.
- Albums first, songs second, with the `notin_` filter so we don't double-delete songs that an expired album already cascades through.
- File unlinks happen *after* commit, same pattern as the existing endpoints.
- Cleanup is the **only** other place besides restore that uses `include_deleted=True`.

## Database migration

Alembic migration:
```python
op.add_column("albums", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
op.add_column("songs",  sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

# Partial indexes — most queries are WHERE deleted_at IS NULL, which a plain
# btree on a mostly-NULL column won't help. The index we *do* want is for the
# cleanup job, which scans for NOT NULL rows past the cutoff.
op.execute("CREATE INDEX ix_albums_deleted_at ON albums (deleted_at) WHERE deleted_at IS NOT NULL")
op.execute("CREATE INDEX ix_songs_deleted_at  ON songs  (deleted_at) WHERE deleted_at IS NOT NULL")
```

## Frontend

- Existing delete confirmation dialog stays the same.
- After successful `DELETE`, show an **undo toast** for 30 seconds: "Album deleted — [Undo]".
- Undo click → `POST .../restore` → on 200, refetch and re-add to the store.
- On 410 from restore, show "Restore window expired" — should be impossible from the toast (30s vs 30d) but handle it for the case where the user navigates back to a stale tab.
- No "trash" view. Keep it simple.

The toast lives in `lib/components/UndoToast.svelte` (new), wired into the store layer so any delete action can dispatch it. Sites that delete:
- Album list / detail view
- Song list / detail view

## Files to change

| File | Changes |
|---|---|
| `db/models.py` | Add `deleted_at` to `Album` and `Song` |
| `db/session.py` | Register `with_loader_criteria` global filter; document the `include_deleted` opt-out |
| `db/queries/albums.py` | `soft_delete_album`, `restore_album`, fix `get_album` to opt-in for restore |
| `db/queries/songs.py` | `soft_delete_song`, `restore_song`, fix `move_song` boundary checks, fix `create_song` track numbering to include deleted |
| `db/queries/playlists.py` | Filter playlist entries by live parent Song/Album |
| `db/queries/__init__.py` | Re-export new functions |
| `album_api.py` | DELETE → soft, add restore endpoint, ownership checks, audit |
| `song_api.py` | DELETE → soft, add restore endpoint, ownership checks, audit |
| `api_models.py` | `RestoreResponse` if needed; `AuditAction.RESTORE` |
| `constants.py` | `RESTORE_WINDOW: Final = timedelta(days=30)` |
| `jobs.py` (or new `cleanup.py`) | `cleanup_expired` periodic task; register in `WorkerSettings.cron_jobs` |
| Alembic migration | `deleted_at` columns + partial indexes |
| `lib/components/UndoToast.svelte` | New |
| Album / Song views | Wire toast into delete flow |
| `scripts/generate_types.py` run | Regenerate `types.ts` |
| Tests | See below |

## Tests (must ship with the code)

Each of these is a real failure mode I can name; the test exists to catch *that specific* mode, not for coverage padding.

- `test_soft_delete_hides_album_from_list` — list endpoints don't return it.
- `test_soft_delete_hides_song_from_get_by_slug` — public share URL 404s.
- `test_soft_delete_hides_song_from_chat_mentions` — @-mention resolution skips it.
- `test_soft_delete_hides_song_from_playlist_entries` — playlist GET filters out the entry.
- `test_restore_album_within_window` — round trip works.
- `test_restore_album_does_not_revive_individually_deleted_songs` — the cascade-timestamp rule.
- `test_restore_album_returns_410_after_window` — explicit window check, independent of cleanup job.
- `test_move_song_rejects_soft_deleted_target` — boundary check.
- `test_move_song_rejects_soft_deleted_source` — boundary check.
- `test_create_song_after_restore_no_track_collision` — soft-deleted songs counted in `max(track_number)`.
- `test_cleanup_expired_hard_deletes_past_cutoff` — including audio files removed.
- `test_cleanup_expired_handles_album_song_double_cascade` — albums first, then orphan songs, no AttributeError on already-deleted children.
- `test_in_flight_generation_lands_on_soft_deleted_song` — generation row exists after delete; cleanup sweeps it later.
- `test_restore_endpoint_enforces_ownership` — another user can't restore your album.
- `test_audit_log_records_delete_and_restore` — both actions appear.

## Not in scope

- Trash / recycle bin view (no UI for browsing soft-deleted items)
- Soft delete for generations (stay hard delete)
- Soft delete for playlists (low value, few items, and entries are already auto-filtered when their parent goes)
- User-configurable retention period (one constant, change it in `constants.py` if needed)
- Multi-user "shared trash" semantics (single-user deployment)

## Open questions

None — every ambiguity from the previous version of this plan is now resolved one way or the other above. If implementation surfaces a new one, update this file before writing code.
