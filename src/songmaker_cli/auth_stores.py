"""songmaker's implementations of the `webauth` store ports.

Each store wraps the matching query functions in `db/queries/auth.py` and
carries the request's session, so everything the auth machinery writes lands
in the transaction the endpoint already owns. None of them commits — the
endpoint decides when the request's work becomes durable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from songmaker_cli.constants import AuditAction, ResourceType
from songmaker_cli.db.queries import (
    count_recent_failed_attempts,
    create_session,
    create_user,
    delete_session,
    delete_user_sessions,
    get_session_with_user,
    get_user,
    get_user_by_username,
    prune_overflow_sessions,
    record_audit,
    record_login_attempt,
    user_count,
)
from webauth.ports import SessionIdentityChange

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

    from songmaker_cli.db.models import User, UserSession
    from webauth.ports import SessionIdentityChanged

AUDITED_SESSION_ID_CHARS: Final = 8
USER_AGENT_CHANGE_DETAIL: Final = "ua_changed"

_AUDIT_ACTIONS: Final = {
    SessionIdentityChange.IP_ADDRESS: AuditAction.SESSION_IP_CHANGE,
    SessionIdentityChange.USER_AGENT: AuditAction.SESSION_UA_CHANGE,
}


@dataclass(frozen=True)
class DatabaseUserStore:
    session: Session

    def get(self, user_id: str) -> User | None:
        return get_user(self.session, user_id)

    def get_by_username(self, username: str) -> User | None:
        return get_user_by_username(self.session, username)

    def count(self) -> int:
        return user_count(self.session)

    def create(self, username: str, password_hash: str, role: str) -> User:
        return create_user(self.session, username, password_hash, role=role)


@dataclass(frozen=True)
class DatabaseSessionRecordStore:
    session: Session

    def create(
        self,
        user_id: str,
        expires_at: datetime,
        *,
        ip_address: str,
        user_agent: str,
    ) -> UserSession:
        return create_session(
            self.session, user_id, expires_at,
            ip_address=ip_address, user_agent=user_agent,
        )

    def load(self, session_id: str) -> UserSession | None:
        return get_session_with_user(self.session, session_id)

    def touch(
        self,
        record: UserSession,
        *,
        ip_address: str,
        user_agent: str,
        expires_at: datetime,
    ) -> None:
        record.ip_address = ip_address
        record.user_agent = user_agent
        record.expires_at = expires_at

    def delete(self, session_id: str) -> None:
        delete_session(self.session, session_id)

    def delete_for_user(self, user_id: str) -> int:
        return delete_user_sessions(self.session, user_id)

    def prune_overflow(self, user_id: str, max_sessions: int) -> list[str]:
        return prune_overflow_sessions(self.session, user_id, max_sessions)


@dataclass(frozen=True)
class DatabaseLoginAttemptStore:
    session: Session

    def record(self, *, ip_address: str, username: str, success: bool) -> None:
        record_login_attempt(self.session, ip_address, username, success=success)

    def count_recent_failures(
        self,
        *,
        ip_address: str,
        window_seconds: int,
        username: str | None = None,
    ) -> int:
        return count_recent_failed_attempts(
            self.session, ip_address, window_seconds, username=username,
        )


@dataclass(frozen=True)
class DatabaseAuditSink:
    session: Session

    def session_identity_changed(self, event: SessionIdentityChanged) -> None:
        record_audit(
            self.session,
            event.user_id,
            _AUDIT_ACTIONS[event.change],
            ResourceType.SESSION,
            event.session_id[:AUDITED_SESSION_ID_CHARS],
            _identity_change_detail(event),
        )


def _identity_change_detail(event: SessionIdentityChanged) -> str:
    if event.change is SessionIdentityChange.IP_ADDRESS:
        return f"from={event.previous} to={event.current}"
    return USER_AGENT_CHANGE_DETAIL
