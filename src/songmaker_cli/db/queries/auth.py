"""Query functions for users, sessions, login attempts, and audit log."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, joinedload

from songmaker_cli.db.models import (
    AuditLog,
    LoginAttempt,
    User,
    UserSession,
)

log = logging.getLogger(__name__)


# ── Users ─────────────────────────────────────────────────────────


def get_user_by_username(session: Session, username: str) -> User | None:
    return session.query(User).filter_by(username=username).first()


def get_user(session: Session, user_id: str) -> User | None:
    return session.query(User).filter_by(id=user_id).first()


def list_users(session: Session) -> list[User]:
    return session.query(User).order_by(User.username).all()


def user_count(session: Session) -> int:
    return session.query(User).count()


def create_user(
    session: Session, username: str, password_hash: str, role: str = "user",
) -> User:
    user = User(username=username, password_hash=password_hash, role=role)
    session.add(user)
    session.flush()
    log.info("Created user '%s' (role=%s)", username, role)
    return user


def update_user(
    session: Session,
    user_id: str,
    role: str | None = None,
    is_active: bool | None = None,
    password_hash: str | None = None,
) -> User:
    user = session.query(User).filter_by(id=user_id).first()
    if not user:
        raise ValueError(f"User not found: {user_id}")
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    if password_hash is not None:
        user.password_hash = password_hash
    session.flush()
    return user


# ── Sessions ──────────────────────────────────────────────────────


def create_session(
    session: Session,
    user_id: str,
    expires_at: datetime,
    ip_address: str = "",
    user_agent: str = "",
) -> UserSession:
    user_session = UserSession(
        user_id=user_id,
        expires_at=expires_at,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(user_session)
    session.flush()
    return user_session


def get_session_with_user(session: Session, session_id: str) -> UserSession | None:
    return (
        session.query(UserSession)
        .options(joinedload(UserSession.user))
        .filter_by(id=session_id)
        .first()
    )


def delete_session(session: Session, session_id: str) -> None:
    user_session = session.query(UserSession).filter_by(id=session_id).first()
    if user_session:
        session.delete(user_session)
        session.flush()


def list_active_sessions(
    session: Session,
    offset: int = 0,
    limit: int | None = None,
) -> list[UserSession]:
    now = datetime.now(timezone.utc)
    query = (
        session.query(UserSession)
        .options(joinedload(UserSession.user))
        .filter(UserSession.expires_at > now)
        .order_by(UserSession.created_at.desc())
        .offset(offset)
    )
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def count_active_sessions(session: Session) -> int:
    now = datetime.now(timezone.utc)
    return session.query(UserSession).filter(UserSession.expires_at > now).count()


def delete_user_sessions(session: Session, user_id: str) -> int:
    """Delete all sessions for a user. Returns count deleted."""
    count = session.query(UserSession).filter_by(user_id=user_id).delete()
    session.flush()
    return count


def delete_expired_sessions(session: Session) -> int:
    now = datetime.now(timezone.utc)
    count = session.query(UserSession).filter(UserSession.expires_at <= now).delete()
    session.flush()
    return count


# ── Login attempts ────────────────────────────────────────────────


def record_login_attempt(
    session: Session, ip_address: str, username: str, *, success: bool,
) -> LoginAttempt:
    attempt = LoginAttempt(
        ip_address=ip_address, username=username, success=success,
    )
    session.add(attempt)
    session.flush()
    return attempt


def count_recent_failed_attempts(
    session: Session,
    ip_address: str,
    window_seconds: int = 300,
    username: str | None = None,
) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    query = session.query(LoginAttempt).filter(
        LoginAttempt.success == False,  # noqa: E712
        LoginAttempt.attempted_at >= cutoff,
    )
    if username:
        query = query.filter(LoginAttempt.username == username)
    else:
        query = query.filter(LoginAttempt.ip_address == ip_address)
    return query.count()


LOGIN_ATTEMPT_RETENTION_DAYS = 90


def cleanup_old_login_attempts(session: Session) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOGIN_ATTEMPT_RETENTION_DAYS)
    count = session.query(LoginAttempt).filter(LoginAttempt.attempted_at < cutoff).delete()
    session.flush()
    return count


def list_login_attempts(
    session: Session,
    offset: int = 0,
    limit: int = 100,
) -> list[LoginAttempt]:
    return (
        session.query(LoginAttempt)
        .order_by(LoginAttempt.attempted_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def count_login_attempts(session: Session) -> int:
    return session.query(LoginAttempt).count()


# ── Audit log ─────────────────────────────────────────────────────


def record_audit(
    session: Session,
    user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str = "",
    detail: str = "",
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
    )
    session.add(entry)
    session.flush()
    return entry


def list_audit_log(
    session: Session,
    offset: int = 0,
    limit: int = 100,
) -> list[AuditLog]:
    return (
        session.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def count_audit_log(session: Session) -> int:
    return session.query(AuditLog).count()
