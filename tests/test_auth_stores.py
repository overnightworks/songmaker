"""The database stores behind the `webauth` ports."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from webauth.ports import (
    AccountEvent,
    AccountEventKind,
    AuditSink,
    SessionRecordStore,
    SubjectUserStore,
)

from songmaker_cli.auth_stores import (
    DatabaseAuditSink,
    DatabaseSessionRecordStore,
    DatabaseSubjectUserStore,
    DatabaseWriteLock,
)
from songmaker_cli.constants import AuditAction, ResourceType
from songmaker_cli.db.engine import connect_db, init_test_db
from songmaker_cli.db.models import AuditLog, Base, ResourceEventCursor, User, UserSession

_SUBJECT = "7b3f0c1e-5d2a-4c88-9e51-0a1b2c3d4e5f"


@pytest.fixture
def session(tmp_path: Path):
    factory = init_test_db(tmp_path / "songmaker.db")
    with factory() as db:
        yield db


@pytest.fixture
def accounts(session) -> SubjectUserStore:
    return DatabaseSubjectUserStore(session)


@pytest.fixture
def sessions(session) -> SessionRecordStore:
    return DatabaseSessionRecordStore(session)


@pytest.fixture
def audit(session) -> AuditSink:
    return DatabaseAuditSink(session)


def _later(hours: int = 1) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def test_an_account_created_for_a_subject_has_the_subject_as_its_id(accounts, session) -> None:
    account = accounts.create_for_subject(_SUBJECT, "nina", "user")
    session.commit()

    assert (account.id, account.username, account.role) == (_SUBJECT, "nina", "user")
    assert session.get(ResourceEventCursor, _SUBJECT) is not None


def test_two_accounts_may_show_the_same_username(accounts) -> None:
    accounts.create_for_subject(_SUBJECT, "nina", "user")

    other = accounts.create_for_subject("another-subject", "nina", "user")

    assert other.username == "nina"


@pytest.mark.parametrize("lookalike", [_SUBJECT.upper(), f"{_SUBJECT} ", f" {_SUBJECT}"])
def test_an_account_is_found_by_its_exact_id_only(accounts, session, lookalike: str) -> None:
    accounts.create_for_subject(_SUBJECT, "nina", "user")
    session.commit()

    assert accounts.get(_SUBJECT) is not None
    assert accounts.get(lookalike) is None


def test_changing_a_role_returns_the_account_and_stays_in_the_callers_transaction(
    accounts, session,
) -> None:
    accounts.create_for_subject(_SUBJECT, "nina", "user")
    session.commit()

    assert accounts.set_role(_SUBJECT, "admin").role == "admin"
    session.rollback()

    assert accounts.get(_SUBJECT).role == "user"


def test_changing_the_role_of_an_unknown_account_raises(accounts) -> None:
    with pytest.raises(ValueError, match="User not found"):
        accounts.set_role("nobody", "admin")


def test_sequential_holds_in_one_transaction_do_not_commit_between_them(accounts, session) -> None:
    accounts.create_for_subject(_SUBJECT, "nina", "user")
    session.commit()
    lock = DatabaseWriteLock(session)

    with lock.hold():
        accounts.set_role(_SUBJECT, "admin")
    with lock.hold():
        accounts.set_role(_SUBJECT, "operator")
    session.rollback()

    assert accounts.get(_SUBJECT).role == "user"


@pytest.mark.parametrize("end_transaction", ["commit", "rollback"])
def test_the_next_hold_locks_again_after_the_transaction_ends(
    session, end_transaction: str,
) -> None:
    statements: list[str] = []
    event.listen(
        session.get_bind(), "before_cursor_execute",
        lambda _conn, _cursor, statement, *_rest: statements.append(statement),
    )
    lock = DatabaseWriteLock(session)

    with lock.hold():
        pass
    with lock.hold():
        pass
    getattr(session, end_transaction)()
    with lock.hold():
        pass

    assert statements.count("BEGIN IMMEDIATE") == 2


def test_management_lock_rejects_pending_business_changes(accounts, session) -> None:
    account = accounts.create_for_subject(_SUBJECT, "nina", "user")
    session.commit()
    account.role = "admin"
    lock = DatabaseWriteLock(session)

    with pytest.raises(AssertionError, match="uncommitted mutations"), lock.hold():
        pass
    session.rollback()
    assert accounts.get(_SUBJECT).role == "user"


def test_a_session_is_stored_with_the_instants_it_is_given(accounts, sessions) -> None:
    accounts.create_for_subject(_SUBJECT, "nina", "user")
    created = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
    expires = created + timedelta(days=7)

    record = sessions.create(_SUBJECT, now=created, expires_at=expires, refresh_token=None)
    loaded = sessions.load(record.id)

    assert loaded.user.username == "nina"
    assert loaded.created_at.replace(tzinfo=timezone.utc) == created
    assert loaded.expires_at.replace(tzinfo=timezone.utc) == expires


def test_a_session_without_a_refresh_token_answers_none(accounts, sessions) -> None:
    accounts.create_for_subject(_SUBJECT, "nina", "user")
    record = sessions.create(_SUBJECT, now=_later(0), expires_at=_later(), refresh_token=None)

    assert sessions.load(record.id).refresh_token is None


def test_a_stored_refresh_token_is_returned_secret_and_kept_out_of_the_repr(
    accounts, sessions, session,
) -> None:
    accounts.create_for_subject(_SUBJECT, "nina", "user")
    record = sessions.create(
        _SUBJECT, now=_later(0), expires_at=_later(), refresh_token=SecretStr("rt-one"),
    )
    session.commit()
    session.expire_all()

    loaded = sessions.load(record.id)

    assert loaded.refresh_token.get_secret_value() == "rt-one"
    assert "rt-one" not in repr(loaded.refresh_token)


def test_a_failed_session_insert_raises_without_the_refresh_token_in_the_traceback(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'production-engine.db'}"
    factory = connect_db(database_url)
    with factory() as database_session:
        Base.metadata.create_all(database_session.get_bind())
        database_session.execute(text("PRAGMA foreign_keys=ON"))
        sessions = DatabaseSessionRecordStore(database_session)

        with pytest.raises(IntegrityError) as failure:
            sessions.create(
                "no-such-account", now=_later(0), expires_at=_later(),
                refresh_token=SecretStr("rt-in-a-failed-insert"),
            )

    formatted = "".join(traceback.format_exception(failure.value))
    assert "rt-in-a-failed-insert" not in formatted


def test_replacing_a_refresh_token_updates_only_an_existing_session(accounts, sessions) -> None:
    accounts.create_for_subject(_SUBJECT, "nina", "user")
    record = sessions.create(
        _SUBJECT, now=_later(0), expires_at=_later(), refresh_token=SecretStr("rt-one"),
    )

    assert sessions.replace_refresh_token(record.id, refresh_token=SecretStr("rt-two")) is True
    assert sessions.load(record.id).refresh_token.get_secret_value() == "rt-two"

    sessions.delete(record.id)

    assert sessions.replace_refresh_token(record.id, refresh_token=SecretStr("rt-three")) is False
    assert sessions.load(record.id) is None


def test_an_unknown_session_is_absent(sessions) -> None:
    assert sessions.load("missing") is None


def test_touching_a_session_writes_the_given_expiry(accounts, sessions) -> None:
    accounts.create_for_subject(_SUBJECT, "nina", "user")
    record = sessions.create(_SUBJECT, now=_later(0), expires_at=_later(1), refresh_token=None)
    renewed = _later(5)

    assert sessions.touch(record.id, expires_at=renewed) is True

    assert sessions.load(record.id).expires_at.replace(tzinfo=timezone.utc) == renewed


@pytest.mark.parametrize("removal", ["missing", "deleted", "revoked"])
def test_touch_does_not_recreate_an_absent_session(accounts, sessions, removal: str) -> None:
    """defect:#1590: stale records cannot resurrect missing or revoked rows."""
    accounts.create_for_subject(_SUBJECT, "nina", "user")
    session_id = "missing"
    if removal != "missing":
        session_id = sessions.create(
            _SUBJECT, now=_later(0), expires_at=_later(), refresh_token=None,
        ).id
        if removal == "deleted":
            sessions.delete(session_id)
        else:
            sessions.delete_for_user(_SUBJECT)

    assert sessions.touch(session_id, expires_at=_later()) is False
    assert sessions.load(session_id) is None


def test_deleting_an_unknown_session_is_not_an_error(sessions) -> None:
    sessions.delete("never-existed")


def test_deleting_a_users_sessions_removes_all_of_them(accounts, sessions, session) -> None:
    accounts.create_for_subject(_SUBJECT, "nina", "user")
    for _ in range(2):
        sessions.create(_SUBJECT, now=_later(0), expires_at=_later(), refresh_token=None)

    assert sessions.delete_for_user(_SUBJECT) == 2
    assert session.query(UserSession).count() == 0


@pytest.mark.parametrize("keep_newest", [0, 1, 2])
def test_pruning_keeps_only_the_newest_sessions(accounts, sessions, keep_newest: int) -> None:
    accounts.create_for_subject(_SUBJECT, "nina", "user")
    base = datetime.now(timezone.utc)
    created = [
        sessions.create(
            _SUBJECT, now=base + timedelta(seconds=index), expires_at=_later(),
            refresh_token=None,
        ).id
        for index in range(3)
    ]

    sessions.prune_overflow(_SUBJECT, keep_newest)

    survivors = [session_id for session_id in created if sessions.load(session_id) is not None]
    assert survivors == created[3 - keep_newest:]


@pytest.mark.parametrize(
    ("kind", "action"),
    [
        (AccountEventKind.USER_CREATED, AuditAction.CREATE),
        (AccountEventKind.ROLE_CHANGED, AuditAction.UPDATE),
    ],
)
def test_account_events_become_audit_lines_without_a_person_behind_them(
    accounts, audit, session, kind: AccountEventKind, action: AuditAction,
) -> None:
    accounts.create_for_subject(_SUBJECT, "nina", "user")
    session.commit()

    audit.account_event(AccountEvent(kind=kind, actor_id=None, subject_id=_SUBJECT, role="admin"))

    entry = session.query(AuditLog).one()
    assert (entry.user_id, entry.action, entry.resource_type, entry.resource_id, entry.detail) == (
        None, action, ResourceType.USER, _SUBJECT, "role=admin",
    )
    session.rollback()
    assert session.query(AuditLog).count() == 0


@dataclass(frozen=True)
class _StoredRows:
    """Everything the auth stores can write, as the database holds it."""

    users: frozenset[str]
    sessions: frozenset[str]
    audit_entries: frozenset[str]

    @classmethod
    def of(cls, session) -> _StoredRows:
        return cls(
            users=frozenset(row.id for row in session.query(User).all()),
            sessions=frozenset(row.id for row in session.query(UserSession).all()),
            audit_entries=frozenset(row.id for row in session.query(AuditLog).all()),
        )


@pytest.mark.parametrize(
    "write",
    [
        pytest.param(
            lambda s: DatabaseSubjectUserStore(s).create_for_subject("rob-subject", "rob", "user"),
            id="creating an account",
        ),
        pytest.param(
            lambda s: DatabaseSessionRecordStore(s).create(
                _SUBJECT, now=_later(0), expires_at=_later(), refresh_token=None,
            ),
            id="creating a session",
        ),
        pytest.param(
            lambda s: DatabaseSessionRecordStore(s).delete_for_user(_SUBJECT),
            id="deleting a user's sessions",
        ),
        pytest.param(
            lambda s: DatabaseSessionRecordStore(s).prune_overflow(_SUBJECT, 0),
            id="pruning sessions",
        ),
        pytest.param(
            lambda s: DatabaseAuditSink(s).account_event(AccountEvent(
                kind=AccountEventKind.USER_CREATED, actor_id=None, subject_id=_SUBJECT, role="user",
            )),
            id="auditing an account event",
        ),
    ],
)
def test_no_store_write_survives_the_endpoints_rollback(session, write) -> None:
    """The endpoint owns the transaction. A request that fails after the auth
    machinery wrote must leave the database exactly as it found it."""
    DatabaseSubjectUserStore(session).create_for_subject(_SUBJECT, "nina", "user")
    DatabaseSessionRecordStore(session).create(
        _SUBJECT, now=_later(0), expires_at=_later(), refresh_token=None,
    )
    session.commit()
    before = _StoredRows.of(session)

    write(session)

    assert _StoredRows.of(session) != before
    session.rollback()
    assert _StoredRows.of(session) == before
