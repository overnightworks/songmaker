# Middleware Refactor: Unify Auth into Dependency Injection

## Problem

Every authenticated request opens **two** SQLite sessions:

1. `SessionMiddleware` (in `server.py`) → creates its own `factory()` session for auth check + session expiry renewal + random cleanup → commits and closes.
2. Endpoint handler → `Depends(get_db_session)` opens a second session for business logic.

This means:
- Double the SQLite connections per request (wasteful on WAL mode).
- Session expiry renewal commits in a separate transaction from the endpoint work. If the endpoint fails after middleware commits, state is inconsistent (session renewed but action not completed).
- The middleware manually manages `db = factory(); try/finally: db.close()` outside FastAPI's dependency lifecycle.

## Goal

Single DB session per request. Auth check, session renewal, and endpoint logic all share one session and commit together.

## Design

### Current Flow

```
Request → BodySizeLimit → SecurityHeaders → AccessLog → SessionMiddleware(own DB) → CORS
  → Endpoint(Depends(get_db_session) → own DB)
```

### Target Flow

```
Request → BodySizeLimit → SecurityHeaders → AccessLog → CORS
  → Endpoint(Depends(get_db_session) → Depends(get_current_user) → shared DB)
```

### Changes

#### 1. Remove `SessionMiddleware` from `server.py`

Delete the `SessionMiddleware` class and its `app.add_middleware(SessionMiddleware)` call.

#### 2. Move auth logic into `get_current_user` dependency

Current `get_current_user` in `middleware.py` just reads `request.state.user`. Refactor it to:

```python
def get_current_user(
    request: Request, db: Session = Depends(get_db_session),
) -> AuthenticatedUser:
    path = request.url.path
    # Public routes don't need auth (but this dependency won't be
    # called on public routes since they don't Depends on it)

    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id or len(session_id) > 64:
        raise HTTPException(401, "Authentication required")

    user_session = get_session_with_user(db, session_id)
    now = datetime.now(timezone.utc)

    # Validate expiry
    expires_at = user_session.expires_at.replace(tzinfo=timezone.utc) if user_session else None
    if not user_session or expires_at < now:
        raise HTTPException(401, "Session expired")

    # Absolute max age
    created_at = user_session.created_at.replace(tzinfo=timezone.utc)
    if (now - created_at).total_seconds() > SESSION_ABSOLUTE_MAX_AGE_SECONDS:
        raise HTTPException(401, "Session expired")

    if not user_session.user.is_active:
        raise HTTPException(403, "Account disabled")

    # Sliding expiry renewal — committed with the endpoint's transaction
    user_session.expires_at = now + timedelta(seconds=SESSION_MAX_AGE_SECONDS)

    return AuthenticatedUser(
        id=user_session.user.id,
        username=user_session.user.username,
        role=user_session.user.role,
        is_active=user_session.user.is_active,
    )
```

Key difference: no separate `db.commit()` — the session renewal is flushed when the endpoint commits.

#### 3. Handle public routes

Public routes (`/api/auth/login`, `/api/auth/setup`, etc.) simply don't have `Depends(get_current_user)`. No middleware needed to skip them.

The SPA fallback and static files are served by FastAPI's route handlers and `StaticFiles` mount — they never hit auth dependencies.

#### 4. Session cleanup

Move the random 1% cleanup to a startup task or a periodic background job instead of piggybacking on request middleware. The lifespan handler already does cleanup on startup — that's sufficient for low-volume usage.

#### 5. Audio endpoint auth

The `get_audio` endpoint in `server.py` currently reads `request.state.user` (set by middleware). Refactor to use `Depends(get_current_user)` like all other endpoints.

### Files Changed

| File | Change |
|------|--------|
| `server.py` | Remove `SessionMiddleware` class and `add_middleware` call |
| `middleware.py` | Rewrite `get_current_user` to do full auth check with DB dependency. Remove `session_auth_middleware`. Keep `_is_public`, `AuthenticatedUser`, `require_admin`. |
| `server.py:get_audio` | Add `user: AuthenticatedUser = Depends(get_current_user)` param |
| `tests/test_middleware.py` | Rewrite to test the new dependency-based auth |
| `tests/test_server.py` | Update audio endpoint tests |

### Migration

This is a single atomic refactor — no gradual migration needed. All tests must pass in one commit.

### Risks

- The `get_audio` endpoint is defined as a closure inside `create_app()`. Adding `Depends` there requires importing `get_current_user` — verify FastAPI resolves nested dependencies correctly in closures.
- Session renewal now commits with the endpoint. If an endpoint raises after auth but before commit, the session is NOT renewed. This is actually better behavior (no side effects on failed requests).

## Priority

Medium — not a bug, but a structural improvement that prevents auth/business logic from diverging in separate transactions.
