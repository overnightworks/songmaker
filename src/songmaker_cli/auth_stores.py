"""songmaker's implementations of the `webauth` store ports.

Each store wraps the matching query functions in `db/queries/auth.py` and
carries the request's session, so everything the auth machinery writes lands
in the transaction the endpoint already owns. None of them commits — the
endpoint decides when the request's work becomes durable.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from sqlalchemy.exc import IntegrityError
from webauth.ports import (
    SessionIdentityChange,
    UnknownUserError,
    UserManagementEventKind,
    UsernameTakenError,
)

from songmaker_cli.api_helpers import _USER_MANAGEMENT_LOCK_ID, _begin_exclusive
from songmaker_cli.constants import AuditAction, ResourceType
from songmaker_cli.db.models import User
from songmaker_cli.db.queries import (
    count_active_sessions,
    count_recent_failed_attempts,
    create_session,
    create_user,
    delete_session,
    delete_user_sessions,
    get_session_with_user,
    get_user,
    get_user_by_username,
    list_active_sessions,
    list_users,
    prune_overflow_sessions,
    record_audit,
    record_login_attempt,
    update_user,
    user_count,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session
    from webauth.ports import SessionIdentityChanged, UserManagementEvent

    from songmaker_cli.db.models import UserSession

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
        try:
            return create_user(self.session, username, password_hash, role=role)
        except IntegrityError:
            # INSERT errors expose password hashes, which the store error contract forbids.
            raise UsernameTakenError("Username already exists") from None

    def list(self) -> list[User]:
        return list_users(self.session)

    def update(
        self,
        user_id: str,
        *,
        role: str | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
    ) -> User:
        try:
            return update_user(
                self.session, user_id, role=role, is_active=is_active,
                password_hash=password_hash,
            )
        except ValueError:
            raise UnknownUserError("Account does not exist") from None

    def count_active_admins(self, role: str) -> int:
        return self.session.query(User).filter_by(role=role, is_active=True).count()


@dataclass
class DatabaseWriteLock:
    """Commit preceding auth work, then retain the lock until the endpoint finishes.

    Nested helpers share the enclosing operation's transaction, so a combined
    account update cannot commit one field before another field fails.
    """

    session: Session
    _held: bool = field(default=False, init=False)

    @contextmanager
    def hold(self) -> Iterator[None]:
        if self._held:
            yield
            return
        assert not self.session.new and not self.session.dirty and not self.session.deleted, (
            "DatabaseWriteLock: session has uncommitted mutations — "
            "the commit() below would persist them unconditionally"
        )
        self.session.commit()
        _begin_exclusive(self.session, _USER_MANAGEMENT_LOCK_ID)
        self._held = True
        try:
            yield
        finally:
            self._held = False


@dataclass(frozen=True)
class DatabaseSessionRecordStore:
    session: Session
    session_max_age_seconds: int

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
        now: datetime,
    ) -> None:
        record.ip_address = ip_address
        record.user_agent = user_agent
        record.expires_at = now + timedelta(seconds=self.session_max_age_seconds)
        self.session.flush()

    def delete(self, session_id: str) -> None:
        delete_session(self.session, session_id)

    def delete_for_user(self, user_id: str) -> int:
        return delete_user_sessions(self.session, user_id)

    def prune_overflow(self, user_id: str, max_sessions: int) -> list[str]:
        return prune_overflow_sessions(self.session, user_id, max_sessions)

    def list_active(self, *, offset: int = 0, limit: int | None = None) -> list[UserSession]:
        return list_active_sessions(self.session, offset=offset, limit=limit)

    def count_active(self) -> int:
        return count_active_sessions(self.session)


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

    def user_updated(self, actor_id: str | None, subject_id: str, detail: str) -> None:
        record_audit(
            self.session, actor_id, AuditAction.UPDATE, ResourceType.USER, subject_id, detail,
        )

    def user_management_event(self, event: UserManagementEvent) -> None:
        match event.kind:
            case UserManagementEventKind.USER_CREATED:
                action, detail = AuditAction.CREATE, f"role={event.role}"
            case UserManagementEventKind.ROLE_CHANGED:
                action, detail = AuditAction.UPDATE, f"role={event.role}"
            case UserManagementEventKind.USER_DEACTIVATED:
                action, detail = AuditAction.DEACTIVATE, ""
            case UserManagementEventKind.PASSWORD_SET_BY_ADMIN:
                action, detail = AuditAction.UPDATE, "password_changed"
            case (
                UserManagementEventKind.FIRST_ADMIN_CREATED
                | UserManagementEventKind.PASSWORD_CHANGED
                | UserManagementEventKind.SESSIONS_REVOKED
                | UserManagementEventKind.SESSION_REVOKED
            ):
                return
            case _:
                raise ValueError(f"Unsupported user management event: {event.kind}")
        if action is AuditAction.UPDATE:
            self.user_updated(event.actor_id, event.subject_id, detail)
        else:
            record_audit(
                self.session, event.actor_id, action, ResourceType.USER, event.subject_id, detail,
            )

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
