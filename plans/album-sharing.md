# Album Sharing

> **Status: NOT STARTED** — small scope, no GPU impact.

## Goal

Let users share finished albums via secret links. Recipients can listen without an account but cannot access the generation engine.

---

## Sharing Types

| Type | Access | URL | Auth Required |
|------|--------|-----|---------------|
| Private (current) | Owner + admin only | N/A | Yes |
| Secret link | Anyone with the link | `/shared/{slug}` | No |
| Public (future) | Everyone | `/albums/{id}` | No |

## Data Model Changes

Add to `Album`:

```python
share_slug: str | None   # unique, uuid-based, nullable
is_shared: bool          # default False
```

Alembic migration to add both columns.

## API Endpoints

```
POST   /api/albums/{id}/share    → generate slug, return share URL
DELETE /api/albums/{id}/share    → revoke sharing
GET    /shared/{slug}            → public read-only album view (no auth)
GET    /shared/{slug}/audio/{f}  → stream MP3 (no auth, rate-limited)
```

## Implementation Steps

- [ ] Add `share_slug` and `is_shared` to Album model + migration
- [ ] `POST /api/albums/{id}/share` — generate UUID slug, set is_shared=True
- [ ] `DELETE /api/albums/{id}/share` — clear slug, set is_shared=False
- [ ] `GET /shared/{slug}` — return album + songs + generations (read-only, no auth)
- [ ] `GET /shared/{slug}/audio/{filename}` — serve MP3 for shared albums
- [ ] Rate limit shared endpoints (prevent scraping)
- [ ] Frontend: "Share" button on album header → copy link, toggle on/off
- [ ] Frontend: `/shared/{slug}` page — read-only player, no sidebar, no edit
- [ ] Tests: sharing flow, revocation, rate limits, no edit access

## Security

- Secret links are UUID v4 (unguessable, 122 bits of entropy)
- Shared view is strictly read-only — no edit, generate, score, or delete
- No user data exposed (no usernames, no edit history, no scores)
- Album owner can revoke sharing instantly
- Rate limit: 60 req/min per IP on shared endpoints

## Frontend: Shared View

Minimal player page:
- Album title + artist
- Song list with play buttons
- Audio player bar
- No sidebar, no editor, no generation controls
- "Made with Songmaker" footer link

---

## Dependencies

None — can start anytime. Small, self-contained feature.
