"""Session-based authentication middleware and FastAPI dependencies."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from songmaker_cli.auth import ROLE_ADMIN, SESSION_MAX_AGE_SECONDS
from songmaker_cli.db.engine import get_session_factory
from songmaker_cli.db.queries import get_session_with_user

log = logging.getLogger(__name__)

SESSION_COOKIE = "session_id"

PUBLIC_PREFIXES = (
    "/api/auth/login",
    "/api/auth/setup",
    "/api/auth/setup-required",
    "/",
    "/login",
    "/setup",
    "/static",
    "/audio/",
    "/_app",
    "/favicon",
)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    username: str
    role: str
    is_active: bool


def _is_public(path: str) -> bool:
    if path in ("/", "/login", "/setup"):
        return True
    return any(path.startswith(p) for p in PUBLIC_PREFIXES if p not in ("/", "/login", "/setup"))


async def session_auth_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    if _is_public(request.url.path):
        return await call_next(request)

    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return JSONResponse({"error": "Authentication required"}, status_code=401)

    factory = get_session_factory()
    db = factory()
    try:
        user_session = get_session_with_user(db, session_id)
        now = datetime.now(timezone.utc)

        expires_at = user_session.expires_at.replace(tzinfo=timezone.utc) if user_session else None
        if not user_session or expires_at < now:
            return JSONResponse({"error": "Session expired"}, status_code=401)

        if not user_session.user.is_active:
            return JSONResponse({"error": "Account disabled"}, status_code=403)

        request.state.user = AuthenticatedUser(
            id=user_session.user.id,
            username=user_session.user.username,
            role=user_session.user.role,
            is_active=user_session.user.is_active,
        )
        request.state.session_id = session_id

        new_expires = now + timedelta(seconds=SESSION_MAX_AGE_SECONDS)
        user_session.expires_at = new_expires
        db.commit()
    finally:
        db.close()

    return await call_next(request)


def get_current_user(request: Request) -> AuthenticatedUser:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Authentication required")
    return user


def require_admin(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    if user.role != ROLE_ADMIN:
        raise HTTPException(403, "Admin access required")
    return user
