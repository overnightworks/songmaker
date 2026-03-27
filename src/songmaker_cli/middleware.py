"""Session-based authentication — FastAPI dependencies (no middleware)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from songmaker_cli.app_context import AppContext, get_db_session
from songmaker_cli.auth import (
    ROLE_ADMIN,
    SESSION_ABSOLUTE_MAX_AGE_SECONDS,
    SESSION_MAX_AGE_SECONDS,
    verify_session_cookie,
)
from songmaker_cli.db.queries import get_session_with_user, record_audit

log = logging.getLogger(__name__)

SESSION_COOKIE = "session_id"


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    username: str
    role: str
    is_active: bool


def get_current_user(
    request: Request, db: Session = Depends(get_db_session),
) -> AuthenticatedUser:
    """Authenticate the request via signed session cookie.

    Performs all auth checks (expiry, absolute lifetime, active user),
    IP/UA change auditing, and sliding session renewal in the same
    DB session as the endpoint — single transaction, single commit.
    """
    ctx: AppContext = request.app.state.ctx

    raw_cookie = request.cookies.get(SESSION_COOKIE)
    if not raw_cookie or len(raw_cookie) > 200:
        raise HTTPException(401, "Authentication required")

    session_id = verify_session_cookie(raw_cookie, ctx.session_secret)
    if session_id is None:
        raise HTTPException(401, "Invalid session")

    request.state.session_id = session_id
    user_session = get_session_with_user(db, session_id)
    now = datetime.now(timezone.utc)

    expires_at = user_session.expires_at.replace(tzinfo=timezone.utc) if user_session else None
    if not user_session or expires_at < now:
        raise HTTPException(401, "Session expired")

    created_at = user_session.created_at.replace(tzinfo=timezone.utc)
    if (now - created_at).total_seconds() > SESSION_ABSOLUTE_MAX_AGE_SECONDS:
        raise HTTPException(401, "Session expired")

    if not user_session.user.is_active:
        raise HTTPException(403, "Account disabled")

    current_ip = request.client.host if request.client else "unknown"
    current_ua = (request.headers.get("user-agent") or "")[:500]
    if user_session.ip_address and user_session.ip_address != current_ip:
        record_audit(
            db, user_session.user.id, "session_ip_change", "session",
            session_id[:8],
            f"from={user_session.ip_address} to={current_ip}",
        )
        user_session.ip_address = current_ip
    if user_session.user_agent and user_session.user_agent != current_ua:
        record_audit(
            db, user_session.user.id, "session_ua_change", "session",
            session_id[:8],
            "ua_changed",
        )
        user_session.user_agent = current_ua

    user_session.expires_at = now + timedelta(seconds=SESSION_MAX_AGE_SECONDS)

    structlog.contextvars.bind_contextvars(user_id=user_session.user.id)

    return AuthenticatedUser(
        id=user_session.user.id,
        username=user_session.user.username,
        role=user_session.user.role,
        is_active=user_session.user.is_active,
    )


def require_admin(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    if user.role != ROLE_ADMIN:
        raise HTTPException(403, "Admin access required")
    return user

