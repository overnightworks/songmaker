"""Session-based authentication middleware and FastAPI dependencies."""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from songmaker_cli.auth import (
    ROLE_ADMIN,
    SESSION_ABSOLUTE_MAX_AGE_SECONDS,
    SESSION_MAX_AGE_SECONDS,
    verify_session_cookie,
)
from songmaker_cli.db.engine import get_session_factory
from songmaker_cli.db.queries import delete_expired_sessions, get_session_with_user, record_audit

log = logging.getLogger(__name__)

SESSION_COOKIE = "session_id"

_PUBLIC_EXACT = frozenset({"/", "/login", "/setup"})

_PUBLIC_PREFIXES = (
    "/api/auth/login",
    "/api/auth/setup",
    "/api/auth/setup-required",
    "/_app/",
    "/favicon.",
)

_SESSION_CLEANUP_PROBABILITY = 0.01


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    username: str
    role: str
    is_active: bool


def _is_public(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    return any(path.startswith(p) for p in _PUBLIC_PREFIXES)


async def session_auth_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    if _is_public(request.url.path):
        return await call_next(request)

    raw_cookie = request.cookies.get(SESSION_COOKIE)
    if not raw_cookie or len(raw_cookie) > 200:
        return JSONResponse({"error": "Authentication required"}, status_code=401)

    session_id = verify_session_cookie(raw_cookie)
    if session_id is None:
        return JSONResponse({"error": "Invalid session"}, status_code=401)

    factory = get_session_factory()
    db = factory()
    try:
        user_session = get_session_with_user(db, session_id)
        now = datetime.now(timezone.utc)

        expires_at = user_session.expires_at.replace(tzinfo=timezone.utc) if user_session else None
        if not user_session or expires_at < now:
            if random.random() < _SESSION_CLEANUP_PROBABILITY:  # noqa: S311
                delete_expired_sessions(db)
                db.commit()
            return JSONResponse({"error": "Session expired"}, status_code=401)

        created_at = user_session.created_at.replace(tzinfo=timezone.utc)
        if (now - created_at).total_seconds() > SESSION_ABSOLUTE_MAX_AGE_SECONDS:
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


# ── IP rate limiter ────────────────────────────────────────────────


class IpRateLimiter:
    """In-memory sliding-window IP rate limiter."""

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._requests: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        with self._lock:
            q = self._requests.get(ip)
            if q is None:
                q = deque()
                self._requests[ip] = q
            while q and q[0] < now - self._window:
                q.popleft()
            if len(q) >= self._max:
                return False
            q.append(now)
            return True
