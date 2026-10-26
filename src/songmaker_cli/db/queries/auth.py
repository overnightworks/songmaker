"""Query functions for users, sessions, and the audit log."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from songmaker_cli.db.models import (
    AuditLog,
    ResourceEventCursor,
    User,
    UserSession,
)

if TYPE_CHECKING:
    from pydantic import SecretStr

log = logging.getLogger(__name__)


# ── Users ─────────────────────────────────────────────────────────


def get_user_by_username(session: Session, username: str) -> User | None:
    """The first account showing ``username``; display names are not unique."""
    return session.query(User).filter_by(username=username).order_by(User.created_at).first()


def get_user(session: Session, user_id: str) -> User | None:
    return session.query(User).filter_by(id=user_id).first()


def create_user(session: Session, user_id: str, username: str, role: str) -> User:
    user = User(id=user_id, username=username, role=role)
    session.add(user)
    session.flush()
    session.add(ResourceEventCursor(user_id=user.id))
    session.flush()
    log.info("Created user %s (role=%s)", user_id, role)
    return user


def set_user_role(session: Session, user_id: str, role: str) -> User:
    user = session.query(User).filter_by(id=user_id).first()
    if not user:
        raise ValueError(f"User not found: {user_id}")
    user.role = role
    session.flush()
    return user


# ── Sessions ──────────────────────────────────────────────────────


def create_session(
    session: Session,
    user_id: str,
    expires_at: datetime,
    refresh_token: SecretStr | None = None,
    id_token: SecretStr | None = None,
) -> UserSession:
    user_session = UserSession(
        user_id=user_id,
        expires_at=expires_at,
        stored_refresh_token=None if refresh_token is None else refresh_token.get_secret_value(),
        stored_id_token=None if id_token is None else id_token.get_secret_value(),
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


def renew_session(
    session: Session,
    session_id: str,
    *,
    expires_at: datetime,
) -> bool:
    """Renew an existing row without recreating a revoked session."""
    rowcount = session.query(UserSession).filter_by(id=session_id).update({
        UserSession.expires_at: expires_at,
    })
    return rowcount == 1


def replace_session_refresh_token(
    session: Session,
    session_id: str,
    refresh_token: SecretStr,
) -> bool:
    """Store the rotated token on an existing row; a deleted session stays deleted."""
    rowcount = session.query(UserSession).filter_by(id=session_id).update({
        UserSession.stored_refresh_token: refresh_token.get_secret_value(),
    })
    return rowcount == 1


def delete_session(session: Session, session_id: str) -> None:
    user_session = session.query(UserSession).filter_by(id=session_id).first()
    if user_session:
        session.delete(user_session)
        session.flush()


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


def prune_overflow_sessions(session: Session, user_id: str, keep_newest: int) -> None:
    """Delete all but the user's ``keep_newest`` newest sessions; ``0`` keeps none."""
    kept = (
        session.query(UserSession.id)
        .filter_by(user_id=user_id)
        .order_by(UserSession.created_at.desc(), UserSession.id.desc())
        .limit(keep_newest)
        .subquery()
    )
    session.query(UserSession).filter(
        UserSession.user_id == user_id, UserSession.id.not_in(select(kept.c.id)),
    ).delete(synchronize_session=False)
    session.flush()


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

