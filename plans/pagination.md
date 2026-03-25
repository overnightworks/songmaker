# Pagination for List Endpoints

## Problem

`list_albums`, `list_songs`, and `list_audit_log` return all records with no limit. `list_songs` does 3 `joinedload` calls (versions, generations+scores, generations+ratings). At ~500 songs x 20 generations each, this becomes a single massive query loading thousands of objects into memory.

## Scope

Backend (queries + API) and frontend (infinite scroll or page buttons). CLI list commands should also respect limits.

## Design

### API Contract

```
GET /api/songs?album_id=X&offset=0&limit=50
GET /api/albums?offset=0&limit=50
```

Response wraps results in a pagination envelope:

```json
{
  "items": [...],
  "total": 142,
  "offset": 0,
  "limit": 50
}
```

### Defaults

| Endpoint | Default limit | Max limit |
|----------|--------------|-----------|
| `/api/albums` | 50 | 200 |
| `/api/songs` | 50 | 200 |
| `/api/audit-log` | 100 | 500 |
| `/api/admin/sessions` | 100 | 500 |
| `/api/admin/login-attempts` | 100 | 500 |

### Backend Changes

1. **`queries.py`**: Add `offset`/`limit` params to `list_albums`, `list_songs`. Add a `count_*` query for total. Keep `light=True` optimization for song list.
2. **`api.py`**: Accept `offset: int = Query(0, ge=0)` and `limit: int = Query(50, ge=1, le=200)`. Return `PaginatedResponse[T]` wrapper.
3. **`api_models.py`**: Add generic `PaginatedResponse` model.
4. **`admin_api.py`**: Same for audit log, sessions, login attempts.
5. **`cli_client.py`**: `api_get` for lists should auto-paginate or accept `--limit`.

### Frontend Changes

1. **`types.ts`**: Add `PaginatedResponse<T>` type.
2. **`client.ts`**: Update `fetchAlbums`, `fetchSongs` to accept pagination params.
3. **`SongList.svelte`**: Infinite scroll or "Load more" button. Track `offset` in store.
4. **`filter.ts`**: Server-side filtering replaces client-side for large lists (future).

### Migration Path

1. Backend: Add `offset`/`limit` with defaults that match current behavior (high limit).
2. Frontend: Update client to pass pagination params.
3. Lower defaults once frontend handles pagination.
4. No breaking change — existing calls without params get the default.

## Not in Scope

- Server-side search/filtering (separate feature)
- Cursor-based pagination (overkill for SQLite)
- Caching layer

## Priority

Low — current scale is fine. Implement when song count approaches ~200 or list load times exceed 500ms.
