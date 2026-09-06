"""What the host application supplies: its users, sessions, attempts, and audit.

Each port is a Protocol the application implements over the persistence it
already owns, so the library needs no schema and no ORM of its own. None of
them commits: the caller owns the transaction boundary, so a request that
fails leaves nothing behind that the auth machinery wrote.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime


class UserRecord(Protocol):
    """The account fields the auth machinery reads."""

    id: str
    username: str
    role: str
    is_active: bool
    password_hash: str


class SessionRecord(Protocol):
    """One stored session and the account it belongs to."""

    id: str
    user_id: str
    ip_address: str
    user_agent: str
    created_at: datetime
    expires_at: datetime
    user: UserRecord


@runtime_checkable
class UserStore(Protocol):
    def get(self, user_id: str) -> UserRecord | None: ...

    def get_by_username(self, username: str) -> UserRecord | None: ...

    def count(self) -> int: ...

    def create(self, username: str, password_hash: str, role: str) -> UserRecord:
        """Add an account, including whatever else the application ties to one."""
        ...


@runtime_checkable
class SessionRecordStore(Protocol):
    def create(
        self,
        user_id: str,
        expires_at: datetime,
        *,
        ip_address: str,
        user_agent: str,
    ) -> SessionRecord: ...

    def load(self, session_id: str) -> SessionRecord | None:
        """The session held against concurrent writers until the caller commits."""
        ...

    def touch(
        self,
        record: SessionRecord,
        *,
        ip_address: str,
        user_agent: str,
        expires_at: datetime,
    ) -> None:
        """Write the current identity and expiry onto ``record`` in place."""
        ...

    def delete(self, session_id: str) -> None: ...

    def delete_for_user(self, user_id: str) -> int: ...

    def prune_overflow(self, user_id: str, max_sessions: int) -> list[str]:
        """Drop the oldest sessions above ``max_sessions``, newest kept."""
        ...


@runtime_checkable
class LoginAttemptStore(Protocol):
    def record(self, *, ip_address: str, username: str, success: bool) -> None: ...

    def count_recent_failures(
        self,
        *,
        ip_address: str,
        window_seconds: int,
        username: str | None = None,
    ) -> int:
        """Failures within the window, by username when given, else by address."""
        ...


class SessionIdentityChange(Enum):
    """Which part of a session's origin stopped matching the stored one."""

    IP_ADDRESS = auto()
    USER_AGENT = auto()


@dataclass(frozen=True)
class SessionIdentityChanged:
    change: SessionIdentityChange
    user_id: str
    session_id: str
    previous: str
    current: str


@runtime_checkable
class AuditSink(Protocol):
    def session_identity_changed(self, event: SessionIdentityChanged) -> None:
        """Record that a live session began arriving from somewhere else."""
        ...
