"""Turning a signed session cookie into the account that made the request.

The application binds these two dependencies once, over the stores it
supplies, and every protected route asks for them. Nothing here commits:
the session renewal and the audit record land in whatever transaction the
application's stores write into, and become durable only when the endpoint
commits it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Final

from fastapi import Depends, HTTPException, Request

from webauth.config import WebAuthConfig, web_auth_config
from webauth.cookies import verify_session_cookie
from webauth.ports import (
    AuditSink,
    SessionIdentityChange,
    SessionIdentityChanged,
    SessionRecordStore,
)
from webauth.proxies import client_user_agent, resolve_client_ip
from webauth.session_store import installed_session_cache

if TYPE_CHECKING:
    from collections.abc import Callable

    from webauth.ports import SessionRecord
    from webauth.session_store import SessionCache

log = logging.getLogger(__name__)

AUTHENTICATION_REQUIRED_DETAIL: Final = "Authentication required"
INVALID_SESSION_DETAIL: Final = "Invalid session"
SESSION_EXPIRED_DETAIL: Final = "Session expired"
ACCOUNT_DISABLED_DETAIL: Final = "Account disabled"
ADMIN_REQUIRED_DETAIL: Final = "Admin access required"

# A signed session cookie is an identifier plus a hex digest; anything much
# longer was not issued here, so it is rejected before any HMAC is computed.
MAX_SESSION_COOKIE_CHARS: Final = 200


@dataclass(frozen=True)
class AuthenticatedUser:
    """The account behind the current request."""

    id: str
    username: str
    role: str
    is_active: bool


@dataclass(frozen=True)
class AuthDependencies:
    """The two route dependencies built from one set of stores.

    ``admin_user`` resolves ``current_user`` itself, so an application that
    replaces one in a test replaces the identity behind both.
    """

    current_user: Callable[..., AuthenticatedUser]
    admin_user: Callable[..., AuthenticatedUser]


def current_user_dependency(
    *,
    session_store: Callable[..., SessionRecordStore],
    audit_sink: Callable[..., AuditSink],
    on_authenticated: Callable[[AuthenticatedUser], None],
) -> AuthDependencies:
    """Bind the auth dependencies to one application's stores.

    ``session_store`` and ``audit_sink`` are the application's own
    dependencies, so whatever transaction it puts them on is the one the
    session renewal and the audit record are written into.
    ``on_authenticated`` is handed the account once the request's identity is
    established, so the application can bind it into its own log context.

    The verified session id is published on ``request.state.session_id``. That
    is part of this contract, not a leftover: a logout route reads it there to
    delete the very session it just authenticated, and dropping the write would
    leave the stored session alive behind a cleared cookie.
    """

    def current_user(
        request: Request,
        sessions: SessionRecordStore = Depends(session_store),
        audit: AuditSink = Depends(audit_sink),
    ) -> AuthenticatedUser:
        config = web_auth_config(request)
        session_id = _session_id_from_cookie(request, config)
        request.state.session_id = session_id

        user = _authenticate_from_cache(request, audit, session_id, config)
        if user is None:
            user = _authenticate_from_store(request, sessions, audit, session_id, config)
        on_authenticated(user)
        return user

    def admin_user(
        request: Request,
        user: AuthenticatedUser = Depends(current_user),
    ) -> AuthenticatedUser:
        if user.role != web_auth_config(request).admin_role:
            raise HTTPException(403, ADMIN_REQUIRED_DETAIL)
        return user

    return AuthDependencies(current_user=current_user, admin_user=admin_user)


def _session_id_from_cookie(request: Request, config: WebAuthConfig) -> str:
    raw_cookie = request.cookies.get(config.session_cookie_name)
    if not raw_cookie or len(raw_cookie) > MAX_SESSION_COOKIE_CHARS:
        raise HTTPException(401, AUTHENTICATION_REQUIRED_DETAIL)
    session_id = verify_session_cookie(raw_cookie, config.signing_key)
    if session_id is None:
        raise HTTPException(401, INVALID_SESSION_DETAIL)
    return session_id


def _record_identity_changes(
    audit: AuditSink,
    *,
    session_id: str,
    user_id: str,
    stored_ip: str,
    stored_user_agent: str,
    current_ip: str,
    current_user_agent: str,
) -> bool:
    """Report each part of the session's origin that stopped matching.

    A session that was stored without an origin at all is not a change.
    """
    ip_changed = bool(stored_ip and stored_ip != current_ip)
    user_agent_changed = bool(stored_user_agent and stored_user_agent != current_user_agent)
    if ip_changed:
        audit.session_identity_changed(
            SessionIdentityChanged(
                change=SessionIdentityChange.IP_ADDRESS,
                user_id=user_id,
                session_id=session_id,
                previous=stored_ip,
                current=current_ip,
            ),
        )
    if user_agent_changed:
        audit.session_identity_changed(
            SessionIdentityChanged(
                change=SessionIdentityChange.USER_AGENT,
                user_id=user_id,
                session_id=session_id,
                previous=stored_user_agent,
                current=current_user_agent,
            ),
        )
    return ip_changed or user_agent_changed


def _reject_session_older_than_absolute_limit(
    created_at: datetime, now: datetime, config: WebAuthConfig,
) -> None:
    if (now - created_at).total_seconds() > config.session_absolute_max_age_seconds:
        raise HTTPException(401, SESSION_EXPIRED_DETAIL)


def _authenticate_from_cache(
    request: Request, audit: AuditSink, session_id: str, config: WebAuthConfig,
) -> AuthenticatedUser | None:
    """The cached account, or None when the cache cannot answer for it."""
    session_cache = installed_session_cache(request.app)
    if session_cache is None:
        return None

    try:
        cached = session_cache.get(session_id)
    except Exception:
        log.warning("Redis session cache read failed, falling back to DB")
        return None

    if cached is None:
        return None

    created_at = cached.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    _reject_session_older_than_absolute_limit(created_at, datetime.now(timezone.utc), config)

    if not cached.is_active:
        raise HTTPException(403, ACCOUNT_DISABLED_DETAIL)

    current_ip = resolve_client_ip(request)
    current_user_agent = client_user_agent(request)

    identity_changed = _record_identity_changes(
        audit,
        session_id=session_id,
        user_id=cached.user_id,
        stored_ip=cached.ip_address,
        stored_user_agent=cached.user_agent,
        current_ip=current_ip,
        current_user_agent=current_user_agent,
    )

    try:
        session_cache.refresh_ttl(session_id, config.session_max_age_seconds)
        if identity_changed:
            session_cache.update_ip_ua(session_id, current_ip, current_user_agent)
    except Exception:
        log.warning("Redis session cache write failed")

    return AuthenticatedUser(
        id=cached.user_id,
        username=cached.username,
        role=cached.role,
        is_active=cached.is_active,
    )


def _authenticate_from_store(
    request: Request,
    sessions: SessionRecordStore,
    audit: AuditSink,
    session_id: str,
    config: WebAuthConfig,
) -> AuthenticatedUser:
    record = sessions.load(session_id)
    now = datetime.now(timezone.utc)
    if record is None or record.expires_at.replace(tzinfo=timezone.utc) < now:
        raise HTTPException(401, SESSION_EXPIRED_DETAIL)

    created_at = record.created_at.replace(tzinfo=timezone.utc)
    _reject_session_older_than_absolute_limit(created_at, now, config)

    if not record.user.is_active:
        raise HTTPException(403, ACCOUNT_DISABLED_DETAIL)

    current_ip = resolve_client_ip(request)
    current_user_agent = client_user_agent(request)

    _record_identity_changes(
        audit,
        session_id=session_id,
        user_id=record.user.id,
        stored_ip=record.ip_address,
        stored_user_agent=record.user_agent,
        current_ip=current_ip,
        current_user_agent=current_user_agent,
    )
    sessions.touch(
        record,
        ip_address=current_ip,
        user_agent=current_user_agent,
        expires_at=now + timedelta(seconds=config.session_max_age_seconds),
    )

    _populate_cache(installed_session_cache(request.app), record, config)

    return AuthenticatedUser(
        id=record.user.id,
        username=record.user.username,
        role=record.user.role,
        is_active=record.user.is_active,
    )


def _populate_cache(
    session_cache: SessionCache | None, record: SessionRecord, config: WebAuthConfig,
) -> None:
    if session_cache is None:
        return
    try:
        session_cache.store(
            record.id, record.user.id, record.user.username,
            record.user.role, record.user.is_active,
            record.ip_address, record.user_agent,
            record.expires_at, record.created_at,
            config.session_max_age_seconds,
        )
    except Exception:
        log.warning("Redis session cache populate failed")
