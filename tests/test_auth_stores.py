"""songmaker's stores behind the webauth ports: what they write, and when."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from songmaker_cli.auth_stores import (
    DatabaseAuditSink,
    DatabaseLoginAttemptStore,
    DatabaseSessionRecordStore,
    DatabaseUserStore,
)
from songmaker_cli.constants import AuditAction
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import (
    AuditLog,
    LoginAttempt,
    ResourceEventCursor,
    User,
    UserSession,
)
from webauth.ports import (
    AuditSink,
    LoginAttemptStore,
    SessionIdentityChange,
    SessionIdentityChanged,
    SessionRecordStore,
    UserStore,
)

_PASSWORD_HASH = "hashed"


@pytest.fixture
def session(tmp_path: Path):
    factory = init_test_db(tmp_path / "songmaker.db")
    with factory() as db:
        yield db


@pytest.fixture
def users(session) -> UserStore:
    return DatabaseUserStore(session)


@pytest.fixture
def sessions(session) -> SessionRecordStore:
    return DatabaseSessionRecordStore(session)


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
        (SessionRecordStore, DatabaseSessionRecordStore),
        (LoginAttemptStore, DatabaseLoginAttemptStore),
        (AuditSink, DatabaseAuditSink),
    ],
)
def test_the_store_answers_everything_its_port_asks(port: type, store: type) -> None:
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


def test_touching_a_session_writes_its_new_origin_onto_the_record(
    users, sessions, session,
) -> None:
    """`touch` hands nothing back: the caller keeps working with the record it
    loaded, so the new origin has to land on that object."""
    user = users.create("nina", _PASSWORD_HASH, "user")
    created = sessions.create(
        user.id, _expiry(), ip_address="1.2.3.4", user_agent="Old/1.0",
    )
    session.commit()
    renewed = _expiry(hours=2)

    sessions.touch(created, ip_address="9.9.9.9", user_agent="New/2.0", expires_at=renewed)

    assert created.ip_address == "9.9.9.9"
    assert created.user_agent == "New/2.0"
    assert created.expires_at == renewed


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
                ip_address="9.9.9.9", user_agent="New/2.0", expires_at=_expiry(hours=2),
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
