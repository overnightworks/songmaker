"""songmaker's stores behind the webauth ports: what they write, and when."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

import pytest
from webauth.ports import (
    AuditSink,
    LoginAttemptStore,
    SessionAdministrationStore,
    SessionIdentityChange,
    SessionIdentityChanged,
    SessionRecordStore,
    UnknownUserError,
    UserAdministrationStore,
    UserManagementEvent,
    UserManagementEventKind,
    UsernameTakenError,
    UserStore,
    WriteLock,
)

from songmaker_cli.auth_stores import (
    DatabaseAuditSink,
    DatabaseLoginAttemptStore,
    DatabaseSessionRecordStore,
    DatabaseUserStore,
    DatabaseWriteLock,
)
from songmaker_cli.constants import AuditAction, ResourceType
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import (
    AuditLog,
    LoginAttempt,
    ResourceEventCursor,
    User,
    UserSession,
)

_PASSWORD_HASH = "hashed"
_SESSION_MAX_AGE_SECONDS = 3600


@pytest.fixture
def session(tmp_path: Path):
    factory = init_test_db(tmp_path / "songmaker.db")
    with factory() as db:
        yield db


@pytest.fixture
def users(session) -> UserStore:
    return DatabaseUserStore(session)


@pytest.fixture
def session_max_age_seconds() -> int:
    return _SESSION_MAX_AGE_SECONDS


@pytest.fixture
def sessions(session, session_max_age_seconds: int) -> SessionRecordStore:
    return DatabaseSessionRecordStore(session, session_max_age_seconds=session_max_age_seconds)


@pytest.fixture
def attempts(session) -> LoginAttemptStore:
    return DatabaseLoginAttemptStore(session)


@pytest.fixture
def audit(session) -> AuditSink:
    return DatabaseAuditSink(session)


def _expiry(hours: int = 1) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


@pytest.mark.parametrize(
    ("port", "store"),
    [
        (UserStore, DatabaseUserStore),
        (UserAdministrationStore, DatabaseUserStore),
        (SessionRecordStore, partial(
            DatabaseSessionRecordStore, session_max_age_seconds=_SESSION_MAX_AGE_SECONDS,
        )),
        (SessionAdministrationStore, partial(
            DatabaseSessionRecordStore, session_max_age_seconds=_SESSION_MAX_AGE_SECONDS,
        )),
        (LoginAttemptStore, DatabaseLoginAttemptStore),
        (AuditSink, DatabaseAuditSink),
        (WriteLock, DatabaseWriteLock),
    ],
)
def test_the_store_answers_everything_its_port_asks(
    port: type, store: Callable[..., object],
) -> None:
    assert isinstance(store(session=None), port)


def test_creating_a_user_also_creates_what_songmaker_ties_to_one(users, session) -> None:
    """Without its event cursor a fresh account replays the whole history on
    its first page load, so the account and the cursor are one creation."""
    created = users.create("nina", _PASSWORD_HASH, "user")

    assert users.get(created.id).username == "nina"
    assert users.get_by_username("nina").id == created.id
    assert users.count() == 1
    assert session.query(ResourceEventCursor).filter_by(user_id=created.id).count() == 1


def test_an_unknown_user_is_absent_rather_than_an_error(users) -> None:
    assert users.get("does-not-exist") is None
    assert users.get_by_username("nobody") is None


def test_duplicate_username_raises_the_port_error(users, session) -> None:
    users.create("nina", _PASSWORD_HASH, "user")
    session.commit()

    with pytest.raises(UsernameTakenError, match="Username already exists"):
        users.create("nina", _PASSWORD_HASH, "admin")

    session.rollback()
    assert users.count() == 1
    assert users.get_by_username("nina").role == "user"


def test_updating_an_unknown_user_raises_the_port_error(users) -> None:
    with pytest.raises(UnknownUserError, match="Account does not exist"):
        users.update("does-not-exist", role="admin")


def test_account_updates_preserve_unsupplied_fields_and_remain_rollbackable(users, session) -> None:
    user = users.create("nina", _PASSWORD_HASH, "user")
    session.commit()

    updated = users.update(user.id, role="admin", is_active=False, password_hash="replacement")

    assert (updated.username, updated.role, updated.is_active, updated.password_hash) == (
        "nina", "admin", False, "replacement",
    )
    session.rollback()
    restored = users.get(user.id)
    assert (restored.role, restored.is_active, restored.password_hash) == (
        "user", True, _PASSWORD_HASH,
    )


def test_accounts_are_listed_in_username_order_and_only_active_matching_roles_count(users) -> None:
    users.create("zoe", _PASSWORD_HASH, "operator")
    inactive = users.create("nina", _PASSWORD_HASH, "operator")
    users.create("anna", _PASSWORD_HASH, "admin")
    users.update(inactive.id, is_active=False)

    assert [user.username for user in users.list()] == ["anna", "nina", "zoe"]
    assert users.count_active_admins("operator") == 1
    assert users.count_active_admins("user") == 0


def test_nested_management_writes_roll_back_together_after_leaving_the_lock(users, session) -> None:
    user = users.create("nina", _PASSWORD_HASH, "user")
    session.commit()
    lock = DatabaseWriteLock(session)

    with lock.hold():
        users.update(user.id, role="admin")
        with lock.hold():
            users.update(user.id, is_active=False)
    session.rollback()

    assert (users.get(user.id).role, users.get(user.id).is_active) == ("user", True)


def test_management_lock_rejects_pending_business_changes(users, session) -> None:
    user = users.create("nina", _PASSWORD_HASH, "user")
    session.commit()
    user.role = "admin"

    with pytest.raises(AssertionError, match="uncommitted mutations"):
        with DatabaseWriteLock(session).hold():
            pass
    session.rollback()
    assert users.get(user.id).role == "user"


def test_a_session_is_loaded_with_the_account_it_belongs_to(users, sessions) -> None:
    user = users.create("nina", _PASSWORD_HASH, "user")

    created = sessions.create(
        user.id, _expiry(), ip_address="1.2.3.4", user_agent="TestBrowser/1.0",
    )

    loaded = sessions.load(created.id)
    assert loaded.id == created.id
    assert loaded.user.username == "nina"
    assert loaded.ip_address == "1.2.3.4"


def test_an_unknown_session_is_absent(sessions) -> None:
    assert sessions.load("does-not-exist") is None


def test_active_session_pages_exclude_expired_records(users, sessions) -> None:
    user = users.create("nina", _PASSWORD_HASH, "user")
    sessions.create(user.id, _expiry(hours=-1), ip_address="", user_agent="")
    older = sessions.create(user.id, _expiry(), ip_address="", user_agent="")
    newer = sessions.create(user.id, _expiry(), ip_address="", user_agent="")

    assert sessions.count_active() == 2
    assert [record.id for record in sessions.list_active(limit=1)] == [newer.id]
    assert [record.id for record in sessions.list_active(offset=1)] == [older.id]
    assert [record.id for record in sessions.list_active()] == [newer.id, older.id]


@pytest.mark.parametrize("session_max_age_seconds", [60, 7200])
def test_touching_a_session_writes_its_new_origin_and_renews_from_the_supplied_time(
    users, sessions, session, session_max_age_seconds: int,
) -> None:
    """`touch` hands nothing back: the caller keeps working with the record it
    loaded, so the new origin has to land on that object."""
    user = users.create("nina", _PASSWORD_HASH, "user")
    created = sessions.create(
        user.id, _expiry(), ip_address="1.2.3.4", user_agent="Old/1.0",
    )
    session.commit()
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)

    sessions.touch(
        created, ip_address="9.9.9.9", user_agent="New/2.0",
        now=now,
    )

    assert created.ip_address == "9.9.9.9"
    assert created.user_agent == "New/2.0"
    assert created.expires_at == now + timedelta(seconds=session_max_age_seconds)


def test_deleting_a_session_leaves_the_others_alone(users, sessions, session) -> None:
    user = users.create("nina", _PASSWORD_HASH, "user")
    kept = sessions.create(user.id, _expiry(), ip_address="", user_agent="")
    dropped = sessions.create(user.id, _expiry(), ip_address="", user_agent="")

    sessions.delete(dropped.id)

    assert sessions.load(dropped.id) is None
    assert sessions.load(kept.id) is not None


def test_deleting_a_users_sessions_removes_all_of_them(users, sessions, session) -> None:
    user = users.create("nina", _PASSWORD_HASH, "user")
    sessions.create(user.id, _expiry(), ip_address="", user_agent="")
    sessions.create(user.id, _expiry(), ip_address="", user_agent="")

    assert sessions.delete_for_user(user.id) == 2
    assert session.query(UserSession).count() == 0


def test_pruning_keeps_the_newest_sessions(users, sessions) -> None:
    user = users.create("nina", _PASSWORD_HASH, "user")
    oldest = sessions.create(user.id, _expiry(), ip_address="", user_agent="")
    newest = sessions.create(user.id, _expiry(), ip_address="", user_agent="")

    assert sessions.prune_overflow(user.id, 1) == [oldest.id]
    assert sessions.load(newest.id) is not None


def test_failures_are_counted_by_address_and_by_username(attempts) -> None:
    attempts.record(ip_address="1.2.3.4", username="nina", success=False)
    attempts.record(ip_address="1.2.3.4", username="rob", success=False)
    attempts.record(ip_address="1.2.3.4", username="nina", success=True)

    assert attempts.count_recent_failures(ip_address="1.2.3.4", window_seconds=300) == 2
    assert attempts.count_recent_failures(
        ip_address="1.2.3.4", window_seconds=300, username="nina",
    ) == 1
    assert attempts.count_recent_failures(ip_address="5.6.7.8", window_seconds=300) == 0


def test_a_moved_session_is_audited_with_where_it_moved(users, audit, session) -> None:
    user = users.create("nina", _PASSWORD_HASH, "user")

    audit.session_identity_changed(SessionIdentityChanged(
        change=SessionIdentityChange.IP_ADDRESS,
        user_id=user.id,
        session_id="0123456789abcdef",
        previous="1.2.3.4",
        current="9.9.9.9",
    ))

    entry = session.query(AuditLog).one()
    assert entry.action == AuditAction.SESSION_IP_CHANGE
    assert entry.resource_id == "01234567"
    assert entry.detail == "from=1.2.3.4 to=9.9.9.9"


def test_a_changed_user_agent_is_audited_without_repeating_the_string(
    users, audit, session,
) -> None:
    """The agent string is attacker-controlled and long; that it changed is
    the finding, the string itself is already on the session."""
    user = users.create("nina", _PASSWORD_HASH, "user")

    audit.session_identity_changed(SessionIdentityChanged(
        change=SessionIdentityChange.USER_AGENT,
        user_id=user.id,
        session_id="0123456789abcdef",
        previous="Old/1.0",
        current="New/2.0",
    ))

    entry = session.query(AuditLog).one()
    assert entry.action == AuditAction.SESSION_UA_CHANGE
    assert entry.detail == "ua_changed"


@pytest.mark.parametrize(
    ("kind", "action", "detail"),
    [
        (UserManagementEventKind.USER_CREATED, AuditAction.CREATE, "role=admin"),
        (UserManagementEventKind.ROLE_CHANGED, AuditAction.UPDATE, "role=admin"),
        (UserManagementEventKind.USER_DEACTIVATED, AuditAction.DEACTIVATE, ""),
        (UserManagementEventKind.PASSWORD_SET_BY_ADMIN, AuditAction.UPDATE, "password_changed"),
        (UserManagementEventKind.FIRST_ADMIN_CREATED, None, None),
        (UserManagementEventKind.PASSWORD_CHANGED, None, None),
        (UserManagementEventKind.SESSIONS_REVOKED, None, None),
        (UserManagementEventKind.SESSION_REVOKED, None, None),
    ],
)
def test_management_events_keep_songmakers_audit_contract(
    users, audit, session, kind, action, detail,
) -> None:
    actor = users.create("nina", _PASSWORD_HASH, "admin")
    subject = users.create("rob", _PASSWORD_HASH, "user")
    session.commit()

    audit.user_management_event(UserManagementEvent(
        kind=kind, actor_id=actor.id, subject_id=subject.id, role="admin",
        session_count=2, session_ref="public-reference",
    ))

    entries = session.query(AuditLog).all()
    if action is None:
        assert entries == []
    else:
        assert len(entries) == 1
        entry = entries[0]
        assert (entry.user_id, entry.resource_type, entry.resource_id) == (
            actor.id, ResourceType.USER, subject.id,
        )
        assert (entry.action, entry.detail) == (action, detail)
    session.rollback()
    assert session.query(AuditLog).count() == 0


@dataclass(frozen=True)
class _StoredRows:
    """Everything the auth stores can write, as the database holds it."""

    users: frozenset[str]
    sessions: frozenset[tuple[str, str, str]]
    login_attempts: frozenset[str]
    audit_entries: frozenset[str]

    @classmethod
    def of(cls, session) -> _StoredRows:
        return cls(
            users=frozenset(row.id for row in session.query(User).all()),
            sessions=frozenset(
                (row.id, row.ip_address, row.user_agent)
                for row in session.query(UserSession).all()
            ),
            login_attempts=frozenset(row.id for row in session.query(LoginAttempt).all()),
            audit_entries=frozenset(row.id for row in session.query(AuditLog).all()),
        )


@dataclass(frozen=True)
class _SeededStores:
    session: object
    users: UserStore
    sessions: SessionRecordStore
    attempts: LoginAttemptStore
    audit: AuditSink
    user_id: str
    session_ids: tuple[str, ...]


@pytest.fixture
def seeded(users, sessions, attempts, audit, session) -> _SeededStores:
    user = users.create("nina", _PASSWORD_HASH, "user")
    first = sessions.create(user.id, _expiry(), ip_address="1.2.3.4", user_agent="Old/1.0")
    second = sessions.create(user.id, _expiry(), ip_address="1.2.3.4", user_agent="Old/1.0")
    session.commit()
    return _SeededStores(
        session=session, users=users, sessions=sessions, attempts=attempts, audit=audit,
        user_id=user.id, session_ids=(first.id, second.id),
    )


@pytest.mark.parametrize(
    "write",
    [
        pytest.param(
            lambda s: s.users.create("rob", _PASSWORD_HASH, "user"), id="creating a user",
        ),
        pytest.param(
            lambda s: s.sessions.create(
                s.user_id, _expiry(), ip_address="5.6.7.8", user_agent="New/2.0",
            ),
            id="creating a session",
        ),
        pytest.param(
            lambda s: s.sessions.touch(
                s.sessions.load(s.session_ids[0]),
                ip_address="9.9.9.9", user_agent="New/2.0", now=_expiry(),
            ),
            id="touching a session",
        ),
        pytest.param(
            lambda s: s.sessions.delete(s.session_ids[0]), id="deleting a session",
        ),
        pytest.param(
            lambda s: s.sessions.delete_for_user(s.user_id), id="deleting a user's sessions",
        ),
        pytest.param(
            lambda s: s.sessions.prune_overflow(s.user_id, 1), id="pruning overflow sessions",
        ),
        pytest.param(
            lambda s: s.attempts.record(
                ip_address="1.2.3.4", username="nina", success=False,
            ),
            id="recording a login attempt",
        ),
        pytest.param(
            lambda s: s.audit.session_identity_changed(SessionIdentityChanged(
                change=SessionIdentityChange.IP_ADDRESS,
                user_id=s.user_id,
                session_id=s.session_ids[0],
                previous="1.2.3.4",
                current="9.9.9.9",
            )),
            id="auditing a moved session",
        ),
    ],
)
def test_no_store_write_survives_the_endpoints_rollback(
    seeded: _SeededStores, write,
) -> None:
    """The endpoint owns the transaction. A request that fails after the auth
    machinery wrote must leave the database exactly as it found it — no half
    session, no orphan audit line, no attempt counted against the visitor."""
    before = _StoredRows.of(seeded.session)

    write(seeded)

    assert _StoredRows.of(seeded.session) != before
    seeded.session.rollback()
    assert _StoredRows.of(seeded.session) == before
