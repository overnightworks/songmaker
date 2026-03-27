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
from songmaker_cli.constants import MAX_USER_AGENT_LENGTH
from songmaker_cli.db.queries import get_session_with_user, record_audit

log = logging.getLogger(__name__)

SESSION_COOKIE = "session_id"


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    username: str
    role: str
    is_active: bool


def _check_ip_ua_changes(
    db: Session,
    session_id: str,
    user_id: str,
    cached_ip: str,
    cached_ua: str,
    current_ip: str,
    current_ua: str,
) -> tuple[bool, bool]:
    ip_changed = bool(cached_ip and cached_ip != current_ip)
    ua_changed = bool(cached_ua and cached_ua != current_ua)
    if ip_changed:
        record_audit(
            db, user_id, "session_ip_change", "session",
            session_id[:8],
            f"from={cached_ip} to={current_ip}",
        )
    if ua_changed:
        record_audit(
            db, user_id, "session_ua_change", "session",
            session_id[:8],
            "ua_changed",
        )
    return ip_changed, ua_changed


def _try_redis_auth(
    request: Request, db: Session, session_id: str,
) -> AuthenticatedUser | None:
    from songmaker_cli.redis_client import SessionCache

    session_cache: SessionCache | None = getattr(request.app.state, "session_cache", None)
    if session_cache is None:
        return None

    try:
        cached = session_cache.get(session_id)
    except Exception:
        log.warning("Redis session cache read failed, falling back to DB")
        return None

    if cached is None:
        return None

    now = datetime.now(timezone.utc)
    created_at = cached["created_at"]
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    if (now - created_at).total_seconds() > SESSION_ABSOLUTE_MAX_AGE_SECONDS:
        raise HTTPException(401, "Session expired")

    if not cached["is_active"]:
        raise HTTPException(403, "Account disabled")

    current_ip = request.client.host if request.client else "unknown"
    current_ua = (request.headers.get("user-agent") or "")[:MAX_USER_AGENT_LENGTH]

    ip_changed, ua_changed = _check_ip_ua_changes(
        db, session_id, cached["user_id"],
        cached["ip_address"], cached["user_agent"],
        current_ip, current_ua,
    )

    try:
        session_cache.refresh_ttl(session_id, SESSION_MAX_AGE_SECONDS)
        if ip_changed or ua_changed:
            session_cache.update_ip_ua(session_id, current_ip, current_ua)
    except Exception:
        log.warning("Redis session cache write failed")

    structlog.contextvars.bind_contextvars(user_id=cached["user_id"])

    return AuthenticatedUser(
        id=cached["user_id"],
        username=cached["username"],
        role=cached["role"],
        is_active=cached["is_active"],
    )


def get_current_user(
    request: Request, db: Session = Depends(get_db_session),
) -> AuthenticatedUser:
    ctx: AppContext = request.app.state.ctx

    raw_cookie = request.cookies.get(SESSION_COOKIE)
    if not raw_cookie or len(raw_cookie) > 200:
        raise HTTPException(401, "Authentication required")

    session_id = verify_session_cookie(raw_cookie, ctx.session_secret)
    if session_id is None:
        raise HTTPException(401, "Invalid session")

    request.state.session_id = session_id

    redis_result = _try_redis_auth(request, db, session_id)
    if redis_result is not None:
        return redis_result

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
    current_ua = (request.headers.get("user-agent") or "")[:MAX_USER_AGENT_LENGTH]

    _check_ip_ua_changes(
        db, session_id, user_session.user.id,
        user_session.ip_address, user_session.user_agent,
        current_ip, current_ua,
    )
    user_session.ip_address = current_ip
    user_session.user_agent = current_ua

    user_session.expires_at = now + timedelta(seconds=SESSION_MAX_AGE_SECONDS)

    try:
        from songmaker_cli.redis_client import SessionCache
        session_cache: SessionCache | None = getattr(request.app.state, "session_cache", None)
        if session_cache:
            session_cache.store(
                session_id, user_session.user.id, user_session.user.username,
                user_session.user.role, user_session.user.is_active,
                current_ip, current_ua,
                user_session.expires_at, user_session.created_at,
                SESSION_MAX_AGE_SECONDS,
            )
    except Exception:
        log.warning("Redis session cache populate failed")

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

