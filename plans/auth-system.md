# Phase 7 — Authentication & Authorization

## Goal

Mandatory login, role-based access control, GPU resource protection. No anonymous access. Secure enough for a server exposed to the internet with friends as users.

## Prerequisites (do first)

- [x] B7: Enable SQLite WAL mode (concurrent reads + writes)
- [x] B8: Set up Alembic migrations (track all schema changes from here on)
- [x] B10: Pydantic response models + eliminated _to_dict layer (from_orm)

---

## Architecture Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Auth method | Session cookies (not JWT) | Revocable, HttpOnly prevents XSS, no client-side token management |
| Password storage | bcrypt via passlib | Offline-capable, no external auth service needed |
| Session storage | SQLite (same DB) | Simple, no Redis needed for single-server |
| Session secret | From env var `SESSION_SECRET` | Never hardcoded. Generate with `openssl rand -hex 32` |
| First-run | Force admin account creation | No default credentials, WordPress-style setup |
| RBAC | admin + user roles | Extensible later (editor, viewer) |
| CSRF | SameSite=Strict + Origin header check | Belt and suspenders |
| SQL injection | SQLAlchemy ORM only | No raw SQL with f-strings anywhere |

---

## Data Model

```python
class User(Base):
    __tablename__ = "users"

    id: str              # uuid
    username: str        # unique, min 3 chars
    password_hash: str   # bcrypt via passlib
    role: str            # "admin" | "user"
    is_active: bool      # soft delete / disable
    created_at: datetime
    updated_at: datetime

class UserSession(Base):
    __tablename__ = "user_sessions"

    id: str              # uuid (this IS the cookie value)
    user_id: str         # FK → User
    created_at: datetime
    expires_at: datetime # 30 days from creation
    ip_address: str      # for audit log
    user_agent: str      # for audit log

class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: str
    ip_address: str
    username: str
    success: bool
    attempted_at: datetime
```

---

## Permission Matrix

| Resource | Admin | User | Anonymous |
|----------|-------|------|-----------|
| GET /api/auth/* (login, setup) | — | — | Yes |
| GET /api/songs, albums, generations | Yes | Yes | No |
| GET /audio/* (play MP3s) | Yes | Yes | No |
| PUT /api/songs/* (edit) | Yes | Yes | No |
| POST /api/songs (create) | Yes | Yes | No |
| POST /api/songs/*/generate | Yes | Rate-limited (3/hour) | No |
| POST /api/generations/*/score | Yes | Rate-limited (10/hour) | No |
| POST /api/chat (Claude) | Yes | Yes (BYOK only) | No |
| DELETE /api/generations/* | Yes | Own only (future) | No |
| DELETE /api/versions/* | Yes | No | No |
| POST /api/albums/*/cleanup | Yes | No | No |
| GET/PUT /api/settings/* | Yes | No | No |
| GET /api/admin/* (user mgmt) | Yes | No | No |
| POST /api/admin/queue/cancel | Yes | No | No |

---

## Security Measures

### 1. Brute-Force Protection
- Max 5 login attempts per IP per 5 minutes
- Track in `login_attempts` table
- After limit: return 429 Too Many Requests with retry-after header
- Admin can see failed attempts in dashboard

### 2. Password Security
- bcrypt with cost factor 12 (passlib)
- Minimum 8 characters, no other silly rules (NIST 800-63)
- Passwords never logged, never returned in API responses

### 3. Session Security
- `SESSION_SECRET` loaded from env var or `.server.env` file
- HttpOnly cookie (JavaScript can't read it)
- Secure flag when behind HTTPS
- SameSite=Strict (no cross-site requests)
- 30-day expiry with sliding window (refreshed on each request)
- Logout invalidates session in DB immediately

### 4. CSRF Protection
- SameSite=Strict on cookie handles most cases
- Additionally check Origin header on all POST/PUT/DELETE requests

### 5. SQL Injection
- All queries through SQLAlchemy ORM (parameterized by default)
- No raw SQL with string interpolation anywhere
- Pydantic validates all input before it reaches queries

### 6. GPU Resource Protection (DoS Prevention)
- Per-user queue limit: max 1 active generation job at a time
- Per-user rate limit: 3 generations/hour for non-admin users
- Admin kill-switch: POST /api/admin/queue/cancel/{job_id}
- Queue depth limit: max 10 total queued jobs
- Generation timeout: 10 minutes per song (kill if exceeded)

---

## API Endpoints

### Auth (public — no session required)

```
GET  /api/auth/setup-required     → { required: bool }
POST /api/auth/setup              { username, password } → Set-Cookie (first admin only)
POST /api/auth/login              { username, password } → Set-Cookie
DELETE /api/auth/session           → Clear cookie (logout)
```

### Auth (authenticated)

```
GET  /api/auth/me                 → { id, username, role }
PUT  /api/auth/password           { current, new } → change own password
```

### Admin

```
GET    /api/admin/users           → list all users
POST   /api/admin/users           { username, password, role }
PUT    /api/admin/users/{id}      { role?, is_active?, password? }
DELETE /api/admin/users/{id}      → deactivate user

GET    /api/admin/login-attempts  → recent failed logins
GET    /api/admin/sessions        → active sessions
DELETE /api/admin/sessions/{id}   → force logout a user

POST   /api/admin/queue/cancel/{job_id} → kill running job
GET    /api/admin/queue           → queue status + GPU info
```

---

## Frontend Changes

### New Pages
- `/login` — login form (public)
- `/setup` — first-run admin creation (public, only when no users)
- `/settings/users` — user management (admin only)
- `/settings/account` — change own password

### Auth Store
```typescript
interface AuthUser {
    id: string;
    username: string;
    role: 'admin' | 'user';
}

export const currentUser = writable<AuthUser | null>(null);
export const isAdmin = derived(currentUser, u => u?.role === 'admin');
```

### Route Protection
- On app load: GET /api/auth/me
  - 401 → redirect to /login
  - 200 → set currentUser store
- Login form: POST /api/auth/login → redirect to /
- Logout: DELETE /api/auth/session → redirect to /login

### UI Adjustments
- Admin-only buttons hidden for users (delete version, cleanup album, settings)
- Rate limit feedback: "Generation limit reached (3/hour). Resets in 45 min."
- Queue status visible to all users
- Admin: "Cancel Job" button on running jobs

---

## Implementation Steps

### Step 1: Dependencies + Models
- [ ] Add `passlib[bcrypt]` to pyproject.toml
- [ ] Add User, UserSession, LoginAttempt models to db/models.py
- [ ] SESSION_SECRET from env var (with helpful error if missing)

### Step 2: Auth Middleware
- [ ] Replace ApiKeyMiddleware with SessionAuthMiddleware
- [ ] Cookie parsing → session lookup → attach user to request
- [ ] Public route allowlist (/api/auth/*, /login, /setup, static assets)
- [ ] Role-checking dependency: `require_admin`

### Step 3: Auth API Endpoints
- [ ] POST /api/auth/setup (first admin creation)
- [ ] POST /api/auth/login (with brute-force protection)
- [ ] DELETE /api/auth/session (logout)
- [ ] GET /api/auth/me
- [ ] GET /api/auth/setup-required
- [ ] PUT /api/auth/password

### Step 4: Admin Endpoints
- [ ] CRUD for users
- [ ] Login attempt viewer
- [ ] Session management (view, force-logout)
- [ ] Queue cancel endpoint

### Step 5: Rate Limiting
- [ ] Per-user generation rate limit (3/hour for users)
- [ ] Per-user scoring rate limit (10/hour for users)
- [ ] Per-user queue depth limit (1 active job)
- [ ] Global queue depth limit (10 jobs)

### Step 6: Frontend — Login + Setup
- [ ] /login page with form
- [ ] /setup page (first-run only)
- [ ] Auth store + route guards
- [ ] Auto-redirect to /login on 401

### Step 7: Frontend — Admin Panel
- [ ] /settings/users page
- [ ] /settings/account page (change password)
- [ ] Queue status with cancel button
- [ ] Failed login attempts viewer

### Step 8: Tests
- [ ] Auth middleware: session validation, expiry, role checking
- [ ] Login: success, failure, brute-force lockout
- [ ] Setup: first admin creation, rejected if admin exists
- [ ] Admin endpoints: user CRUD, session management
- [ ] Rate limiting: generation/scoring limits, queue depth
- [ ] Frontend: auth store, login flow, route guards

### Step 9: Documentation
- [ ] Update CLAUDE.md with auth setup instructions
- [ ] Document SESSION_SECRET generation
- [ ] Document first-run setup flow
- [ ] Update API contract section

---

## Configuration

```bash
# Required for server startup (generate with: openssl rand -hex 32)
SESSION_SECRET=your-64-char-hex-string

# Optional overrides
SESSION_MAX_AGE=2592000          # 30 days in seconds
LOGIN_RATE_LIMIT=5               # attempts per 5 minutes
GENERATION_RATE_LIMIT_USER=3     # per hour for non-admin
SCORING_RATE_LIMIT_USER=10       # per hour for non-admin
MAX_QUEUE_DEPTH=10               # total queued jobs
```

Load from `.server.env` file (gitignored) or environment variables.

---

## What This Does NOT Include (Future)

- OAuth2/OIDC (Google/GitHub login) — add as additional login method
- Multi-tenancy (per-user song isolation) — all users see all songs for now
- API tokens for programmatic access — add for CI/CD later
- 2FA/TOTP — add when deploying publicly
- Email verification — not needed for invite-only use
- Password reset flow — admin can reset via admin panel

---

## Migration Notes

- Existing server.env with SONGMAKER_API_KEY continues to work during migration
- Add SESSION_SECRET to .server.env
- On first startup after migration: /setup page appears
- Old ApiKeyMiddleware removed after auth is live
- Existing DB gets User + UserSession + LoginAttempt tables via create_all
