# Soft Delete Plan

## Goal

Albums and songs get soft delete with undo capability. Generations stay hard delete.

## Design

### Database

Add `deleted_at: DateTime | None` column to `Album` and `Song` models. Default `None` (not deleted).

When a user "deletes" an album or song:
- Set `deleted_at = now()`
- The record stays in the DB with all related data intact

### Query filters

Every query that lists or fetches albums/songs adds `.filter(Album.deleted_at.is_(None))` (or Song). This means soft-deleted records are invisible to the user everywhere — sidebar, API responses, search, playlists.

Exception: the undo/restore endpoint (see below) fetches by ID regardless of `deleted_at`.

### Undo flow

1. User clicks "Delete Album" → confirmation dialog shows blast radius → user confirms
2. Backend sets `deleted_at = now()`, returns success
3. Frontend shows an **undo toast** for 30 seconds: "Album deleted — [Undo]"
4. If user clicks Undo within 30s → `POST /api/albums/{id}/restore` → sets `deleted_at = None`
5. If toast expires → nothing happens, record stays soft-deleted

### Permanent cleanup

A background job (arq periodic task or cron) runs daily:
- Query all albums/songs where `deleted_at < now() - 30 days`
- Hard delete: remove all generations (+ audio files), versions, chat messages, scores, ratings
- Delete the song/album record itself
- Log what was cleaned up

### API changes

**Albums:**
- `DELETE /api/albums/{id}` — changes from hard delete to soft delete (set `deleted_at`)
- `POST /api/albums/{id}/restore` — new endpoint, clears `deleted_at`. Returns 404 if not found or already permanently deleted. Only works within 30-day window.

**Songs:**
- `DELETE /api/songs/{id}` — changes from hard delete to soft delete
- `POST /api/songs/{id}/restore` — new endpoint, clears `deleted_at`

**Cascading:**
- Deleting an album soft-deletes all its songs too (set `deleted_at` on each song)
- Restoring an album restores all its songs
- Deleting a song only soft-deletes that song, not the album

### Frontend changes

- Delete confirmation dialog (implemented separately, see ui-polish plan) stays the same
- After successful delete, show undo toast with 30s countdown
- Undo toast calls restore endpoint, re-fetches and re-adds to store
- No "trash" view — keep it simple

### Migration

Alembic migration:
- Add `deleted_at` column (nullable DateTime) to `albums` and `songs` tables
- Add index on `deleted_at` for efficient filtering

### Files to change

| File | Changes |
|---|---|
| `db/models.py` | Add `deleted_at` to Album and Song |
| `db/queries/albums.py` | Filter by `deleted_at.is_(None)` in list/get, add `soft_delete_album`, `restore_album` |
| `db/queries/songs.py` | Same pattern, add `soft_delete_song`, `restore_song` |
| `album_api.py` | Change delete to soft delete, add restore endpoint |
| `song_api.py` | Change delete to soft delete, add restore endpoint |
| `api_models.py` | Add `RestoreResponse` if needed |
| `jobs.py` or new `cleanup.py` | Periodic hard-delete job for expired soft deletes |
| `AlbumDetailView.svelte` | Undo toast after delete |
| `SongDetailView.svelte` | Undo toast after delete |
| Alembic migration | Add `deleted_at` column |
| Tests | Soft delete, restore, expiry, cascade |

## Not in scope

- Trash/recycle bin view
- Soft delete for generations (stay hard delete)
- Soft delete for playlists (low value, few items)
- User-configurable retention period
