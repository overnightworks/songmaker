# Migration: Session & Auth Scaling

> **Status: NOT STARTED** — needed when per-request DB writes become a bottleneck.
> **Depends on: Redis migration + PostgreSQL migration**

## Problem

Every authenticated request writes to the DB: session `expires_at` is updated at `middleware.py:89` (sliding window renewal). IP/UA changes trigger audit records at `middleware.py:74-87`. Under concurrent users with multiple uvicorn workers, this creates write contention on session rows.

Authentication is username/password only — no OAuth, SSO, or MFA.

## Precise Impact Analysis

**Per-request DB writes in `get_current_user()` (`middleware.py:38-98`)**:

| Write | Line | Frequency | Cost |
|-------|------|-----------|------|
| `user_session.expires_at = now + timedelta(...)` | 89 | EVERY authenticated request | UPDATE on sessions table |
| `record_audit(session, ..., "ip_change", ...)` | 79 | Only when IP changes (rare) | INSERT into audit_log |
| `user_session.ip_address = ip` | 80 | Only when IP changes | UPDATE on sessions table |
| `record_audit(session, ..., "ua_change", ...)` | 86 | Only when UA changes (rare) | INSERT into audit_log |
| `user_session.user_agent = ua` | 87 | Only when UA changes | UPDATE on sessions table |

The `expires_at` update is the bottleneck — it happens on EVERY request. The IP/UA audit writes are rare and acceptable.

**Transaction coupling**: The session renewal happens in the SAME SQLAlchemy session as the endpoint logic. The endpoint's `session.commit()` persists both the session renewal AND the endpoint's mutations atomically. Deferring the session renewal to Redis breaks this atomicity — but that's acceptable because session renewal is best-effort (a stale `expires_at` by a few minutes doesn't matter).

## Goal

Reduce per-request DB writes for session validation. Add OAuth/SSO support for team deployments. Add optional MFA.

## Priorities

1. **Redis session cache** — reduces DB writes from every request to periodic sync
2. **JWT option** — stateless auth, zero DB hits per request (trade-off: no server-side revocation)
3. **OAuth/SSO** — enterprise requirement, not a scaling fix
4. **MFA** — security hardening, not a scaling fix

## Steps

### Phase 1: Redis session cache

**Strategy**: Redis as primary session store for reads, DB synced periodically for durability.

- [ ] On login (`auth_api.py:192-202`): write session to BOTH DB and Redis:
  ```
  SET session:{id} {json: user_id, role, is_active, ip, ua, expires_at} EX {max_age}
  ```

- [ ] On request (`middleware.py:38-98`): check Redis first, fall back to DB on miss:
  ```python
  cached = redis.get(f"session:{session_id}")
  if cached:
      data = json.loads(cached)
      # Verify is_active, check expiry — from cached data
      # Update Redis TTL (cheap, replaces per-request DB write)
      redis.expire(f"session:{session_id}", SESSION_MAX_AGE_SECONDS)
  else:
      # Redis miss: load from DB (current path)
      user_session = get_session_with_user(db, session_id)
      # ... validate ...
      # Populate Redis cache for next request
      redis.set(f"session:{session_id}", json.dumps({...}), ex=SESSION_MAX_AGE_SECONDS)
  ```

- [ ] **Session renewal DB sync**: Instead of updating `expires_at` on every request, sync to DB every 5 minutes:
  - Redis tracks real-time `expires_at` (updated every request via TTL)
  - Background task (Celery Beat or async) bulk-syncs active sessions to DB periodically
  - If Redis dies, DB has a value that's at most 5 minutes stale — within tolerance

- [ ] IP/UA change detection: compare against Redis-cached values:
  - If changed: write audit to DB immediately (rare, acceptable)
  - If unchanged: no DB write (common case, big win)
  - Update Redis cache with new IP/UA

- [ ] On logout (`auth_api.py:213-216`): delete from BOTH Redis and DB
  - Redis: `DEL session:{session_id}`
  - DB: `delete_session(db, session_id)` (current)

- [ ] On user deactivation (`admin_api.py:129-130`): delete all user sessions from BOTH Redis and DB
  - Redis: scan for `session:*` keys belonging to user (store user_id→session_ids mapping in Redis set)
  - DB: `delete_user_sessions(db, user_id)` (current)

- [ ] **Redis failure fallback**: If Redis is down, fall back to DB-only (current behavior). Every Redis call is wrapped in try/except. Log warning on Redis failure, continue with DB path.

- [ ] **Audit trail continuity**: IP/UA change audit records continue to be written to DB (they're rare). The only thing deferred is `expires_at` — which is operational state, not an audit concern.

### Phase 2: JWT alternative (optional, deferred)

- [ ] Stateless JWT with short expiry (15 min) + refresh token in DB
- [ ] Access token: contains user ID, role, expiry — verified by signature only
- [ ] Refresh token: stored in DB, used to get new access tokens
- [ ] Trade-off: can't revoke access tokens until they expire (15 min window)
- [ ] Use case: high-traffic API clients, mobile apps
- [ ] **Decision: defer** — Redis session cache solves the scaling problem without losing revocation

### Phase 3: OAuth/SSO (future)

- [ ] Add `authlib` dependency
- [ ] Support: Google, GitHub (most common for developer tools)
- [ ] Flow: OAuth redirect → callback → create/link user → session cookie
- [ ] User table changes: add `oauth_provider` (String 20, nullable), `oauth_id` (String 200, nullable)
- [ ] Alembic migration for new columns
- [ ] Config: `OAUTH_GOOGLE_CLIENT_ID`, `OAUTH_GOOGLE_CLIENT_SECRET` env vars
- [ ] Preserve existing username/password as fallback
- [ ] Admin can disable password auth when OAuth is configured

### Phase 4: MFA (future)

- [ ] TOTP (Google Authenticator / Authy) — `pyotp` library
- [ ] User table changes: add `mfa_secret` (String 100, nullable), `mfa_enabled` (Boolean, default False)
- [ ] Alembic migration for new columns
- [ ] Login flow: password → 200 with `mfa_required: true` → second request with TOTP code
- [ ] Recovery codes: 10 single-use codes stored hashed in DB
- [ ] Admin can enforce MFA for all users

## Design Decisions

### Redis session vs JWT
Redis session is simpler, preserves all current behavior (server-side revocation, sliding window), and is a natural extension of the Redis migration. JWT is more scalable but loses revocation. **Decision: Redis session first, JWT only if needed for specific use cases.**

### Session sync frequency
Every 5 minutes per session. `expires_at` in Redis is the real-time value (TTL-based). DB gets updated in background. If Redis dies, DB has a value that's at most 5 minutes stale — within the `SESSION_MAX_AGE_SECONDS` (30 days) tolerance.

### Transaction atomicity
Current: session renewal and endpoint mutations share one `session.commit()`. After migration: session renewal is in Redis (separate from DB transaction). This means a failed endpoint commit no longer rolls back the session renewal — but that's correct behavior. Session renewal should succeed even if the endpoint fails.

### User deactivation with Redis
When admin deactivates a user (`admin_api.py:129-130`), all sessions must be immediately invalidated. With Redis: maintain a `user_sessions:{user_id}` Redis set containing all active session IDs. On deactivation, iterate and `DEL` each. On login, `SADD user_sessions:{user_id} {session_id}`. On logout, `SREM`.

## Testing

- Redis session: verify login → Redis populated, request → Redis hit (no DB query for session), logout → both cleared
- Failover: kill Redis → requests still work via DB fallback
- Deactivation: deactivate user → verify Redis sessions deleted, next request returns 403
- IP change: change IP → verify audit log written to DB, Redis cache updated
- Sync: verify DB `expires_at` updates periodically (not per-request)
- OAuth: mock OAuth provider, verify user creation and session
