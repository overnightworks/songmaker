"""songmaker's implementations of the `webauth` store ports.

Each store wraps the matching query functions in `db/queries/auth.py` and
carries its caller's session. None of them commits: authentication owns a
short transaction, while endpoint and stream callers own their transactions.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from webauth.ports import AccountEventKind, SignInStores

from songmaker_cli.api_helpers import (
    _USER_MANAGEMENT_LOCK_ID,
    _begin_exclusive,
    end_read_transaction_before_lock,
)
from songmaker_cli.constants import AuditAction, ResourceType
from songmaker_cli.db.models import USERNAME_MAX_LENGTH
from songmaker_cli.db.queries.auth import (
    create_session,
    create_user,
    delete_session,
    delete_user_sessions,
    get_session_with_user,
    get_user,
    prune_overflow_sessions,
    record_audit,
    renew_session,
    replace_session_refresh_token,
    set_user_kind,
    set_user_role,
)

if TYPE_CHECKING:
    from datetime import datetime

    from pydantic import SecretStr
    from sqlalchemy.orm import Session, SessionTransaction, sessionmaker
    from webauth.ports import AccountEvent, AccountKind

    from songmaker_cli.db.models import User, UserSession


@dataclass(frozen=True)
class DatabaseSubjectUserStore:
    """Accounts keyed by the issuer's subject; the account id is that subject."""

    session: Session

    def get(self, user_id: str) -> User | None:
        return get_user(self.session, user_id)

    def create_for_subject(
        self, subject: str, username: str, role: str, kind: AccountKind,
    ) -> User:
        """The username is display text and may be longer than the column holds."""
        return create_user(self.session, subject, username[:USERNAME_MAX_LENGTH], role, kind)

    def set_role(self, user_id: str, role: str) -> User:
        return set_user_role(self.session, user_id, role)

    def set_kind(self, user_id: str, kind: AccountKind) -> User:
        return set_user_kind(self.session, user_id, kind)


@dataclass
class DatabaseWriteLock:
    """End the open transaction, which must hold no write, then keep the lock until it ends.

    The lock is tracked per transaction: a further hold in the same transaction,
    nested or sequential, neither commits nor takes the lock again, so a combined
    update cannot persist one part before another fails. After a commit or a
    rollback the next hold locks again.
    """

    session: Session
    _locked_transaction: SessionTransaction | None = field(default=None, init=False)

    @contextmanager
    def hold(self) -> Iterator[None]:
        if not self._holds_current_transaction():
            self._lock_new_transaction()
        yield

    def _holds_current_transaction(self) -> bool:
        current = self.session.get_transaction()
        return current is not None and current is self._locked_transaction

    def _lock_new_transaction(self) -> None:
        end_read_transaction_before_lock(self.session, "DatabaseWriteLock")
        _begin_exclusive(self.session, _USER_MANAGEMENT_LOCK_ID)
        self._locked_transaction = self.session.get_transaction()


@dataclass(frozen=True)
class DatabaseSessionRecordStore:
    session: Session

    def create(
        self,
        user_id: str,
        *,
        now: datetime,
        expires_at: datetime,
        refresh_token: SecretStr | None,
        id_token: SecretStr | None,
    ) -> UserSession:
        record = create_session(self.session, user_id, expires_at, refresh_token, id_token)
        record.created_at = now
        self.session.flush()
        return record

    def load(self, session_id: str) -> UserSession | None:
        return get_session_with_user(self.session, session_id)

    def touch(self, session_id: str, *, expires_at: datetime) -> bool:
        return renew_session(self.session, session_id, expires_at=expires_at)

    def replace_refresh_token(self, session_id: str, *, refresh_token: SecretStr) -> bool:
        return replace_session_refresh_token(self.session, session_id, refresh_token)

    def delete(self, session_id: str) -> None:
        delete_session(self.session, session_id)

    def delete_for_user(self, user_id: str) -> int:
        return delete_user_sessions(self.session, user_id)

    def prune_overflow(self, user_id: str, keep_newest: int) -> None:
        prune_overflow_sessions(self.session, user_id, keep_newest)


@dataclass(frozen=True)
class DatabaseSessionTransaction:
    """The short transaction webauth wraps around its session-store calls.

    Each entry opens its own database session and commits on a clean exit; closing the session
    rolls back anything else. A rotated refresh token is therefore durable before the library
    hands out a token.
    """

    factory: sessionmaker[Session]

    @contextmanager
    def __call__(self) -> Iterator[DatabaseSessionRecordStore]:
        with self.factory() as session:
            yield DatabaseSessionRecordStore(session)
            session.commit()


@dataclass(frozen=True)
class DatabaseAuditSink:
    session: Session

    def account_event(self, event: AccountEvent) -> None:
        detail = f"role={event.role}"
        match event.kind:
            case AccountEventKind.USER_CREATED:
                action = AuditAction.CREATE
            case AccountEventKind.ROLE_CHANGED:
                action = AuditAction.UPDATE
            case AccountEventKind.KIND_CHANGED:
                action = AuditAction.UPDATE
                detail = f"kind={event.previous_account_kind}->{event.account_kind}"
            case AccountEventKind.BACKCHANNEL_LOGOUT:
                record_audit(
                    self.session, event.actor_id, AuditAction.DELETE, ResourceType.SESSION,
                    event.subject_id, "back-channel logout",
                )
                return
            case _:
                raise ValueError(f"Unsupported account event: {event.kind}")
        record_audit(
            self.session, event.actor_id, action, ResourceType.USER, event.subject_id, detail,
        )


@dataclass(frozen=True)
class DatabaseSignInTransaction:
    """The serialized context around one sign-in entry.

    Each entry opens its own database session and takes the user-management lock; a clean exit
    commits; an exception leaves the block and the session closes with its transaction rolled
    back, so a failed entry (a deletion followed by a failing audit write) persists nothing.
    """

    factory: sessionmaker[Session]

    @contextmanager
    def __call__(self) -> Iterator[SignInStores]:
        with self.factory() as session:
            with DatabaseWriteLock(session).hold():
                yield SignInStores(
                    accounts=DatabaseSubjectUserStore(session),
                    sessions=DatabaseSessionRecordStore(session),
                    audit=DatabaseAuditSink(session),
                )
            session.commit()
