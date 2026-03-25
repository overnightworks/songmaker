# Phase 7 — Authentication & Authorization

> **Status: COMPLETE** — all steps implemented and tested (505 Python + 131 frontend tests).

## Goal

Mandatory login, role-based access control, GPU resource protection. No anonymous access. Secure enough for a server exposed to the internet with friends as users.

## What Was Built

### Architecture Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Auth method | Session cookies (not JWT) | Revocable, HttpOnly prevents XSS, no client-side token management |
| Password storage | bcrypt (12 rounds) | Offline-capable, no external auth service needed |
| Session storage | SQLite (same DB) | Simple, no Redis needed for single-server |
| Session secret | `SESSION_SECRET` env var | Never hardcoded. Generate with `openssl rand -hex 32` |
| First-run | Force admin account creation via /setup | No default credentials |
| RBAC | admin + user roles | Extensible later (editor, viewer) |
| CSRF | SameSite=Lax + HttpOnly cookies | Standard defense |
| SQL injection | SQLAlchemy ORM only, Pydantic validation | No raw SQL anywhere |

### Data Model

- `User` — id, username, password_hash, role (admin/user), is_active
- `UserSession` — id (= cookie value), user_id (FK), expires_at, ip_address, user_agent
- `LoginAttempt` — id, ip_address, username, success, attempted_at
- `Album.created_by` — FK → User.id (SET NULL on delete)
- `Job.user_id` — FK → User.id (SET NULL on delete)

### Security Measures

| Measure | Implementation |
|---------|---------------|
| Brute-force | 5 attempts per IP per 5min → 429 with Retry-After |
| Password | bcrypt cost 12, min 8 chars (NIST 800-63) |
| Session cookies | HttpOnly, SameSite=Lax, 30-day sliding window |
| Session invalidation | Logout deletes from DB, stale jobs recovered on restart |
| Rate limiting | 3 gen/hr + 10 score/hr per user, 1 active job, 10 queue depth |
| Path traversal | Audio endpoint validates paths, checks album ownership |
| Input validation | Pydantic models on all API inputs |

### Permission Matrix

| Resource | Admin | User | Anonymous |
|----------|-------|------|-----------|
| Auth endpoints (login, setup) | — | — | Yes |
| Songs, albums, generations | All | Own albums only | No |
| Audio playback | All | Own albums only | No |
| Generate (GPU) | Unlimited | 3/hour, 1 active | No |
| Score (GPU) | Unlimited | 10/hour | No |
| Claude chat | Yes | Yes (BYOK) | No |
| Admin endpoints | Yes | No | No |
| Settings | Yes | No | No |
| Cleanup / delete | Yes | No | No |

### API Endpoints

**Auth (public)**:
`GET /api/auth/setup-required`, `POST /api/auth/setup`, `POST /api/auth/login`, `DELETE /api/auth/session`, `GET /api/auth/me`, `PUT /api/auth/password`

**Admin**:
`GET/POST/PUT/DELETE /api/admin/users`, `GET /api/admin/login-attempts`, `GET/DELETE /api/admin/sessions`, `POST /api/admin/acestep/reinitialize`, `GET /api/admin/acestep/status`

### Frontend Pages

- `/login` — login form
- `/setup` — first-run admin creation
- `/settings/users` — admin user management
- `/settings/account` — change own password

### Configuration

```bash
SESSION_SECRET=your-64-char-hex-string    # required (openssl rand -hex 32)
SESSION_MAX_AGE=2592000                   # 30 days (optional)
LOGIN_RATE_LIMIT=5                        # per 5min (optional)
GENERATION_RATE_LIMIT_USER=3              # per hour (optional)
SCORING_RATE_LIMIT_USER=10                # per hour (optional)
MAX_QUEUE_DEPTH=10                        # total queued jobs (optional)
```

---

## Future Extensions (not started)

| Feature | Schema Change | Effort |
|---------|--------------|--------|
| Share albums with specific users | New `AlbumShare(album_id, user_id, permission)` table | Medium |
| Public album links | `Album.is_public` + `Album.share_slug` | Small |
| OAuth2/OIDC (Google/GitHub login) | Additional login method | Medium |
| API tokens for programmatic access | New `ApiToken` model | Small |
| 2FA/TOTP | `User.totp_secret` | Medium |
| Admin queue cancel | `POST /api/admin/queue/cancel/{job_id}` | Small |
