"""PostgreSQL-specific tests.

Tests requiring a live PostgreSQL instance are skipped unless
TEST_DATABASE_URL is set to a PostgreSQL URL.

Run with: TEST_DATABASE_URL=postgresql://user:pass@localhost/test pytest tests/test_postgresql.py
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.api_helpers import _SESSION_CAP_LOCK_ID, _begin_exclusive
from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import JobStatus, JobType, LoraStatus
from songmaker_cli.db.engine import (
    init_test_db,
    resolve_database_url,
)
from songmaker_cli.db.models import (
    Album,
    AuditLog,
    Base,
    Generation,
    Job,
    ResourceEventCursor,
    Song,
    User,
    UserLora,
    UserSession,
)
from songmaker_cli.db.queries import (
    create_generation_created_event,
    create_job,
    create_session,
    delete_resource_events_before,
    get_oldest_resource_event_sequence,
    get_resource_event_high_water_mark,
    job_duration_stats,
    list_resource_events_after,
    prune_overflow_sessions,
)
from songmaker_cli.lifecycle import reconcile_crashed_loras
from songmaker_cli.settings import get_settings

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
SKIP_NO_PG = pytest.mark.skipif(
    not TEST_PG_URL.startswith("postgresql"),
    reason="TEST_DATABASE_URL not set to a PostgreSQL URL",
)


def _pg_session_factory() -> sessionmaker[Session]:
    settings = get_settings()
    engine = create_engine(
        TEST_PG_URL,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
    )
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def sqlite_factory(tmp_path: Path) -> sessionmaker[Session]:
    return init_test_db(tmp_path / "test.db")


@pytest.fixture()
def pg_factory():
    if not TEST_PG_URL.startswith("postgresql"):
        pytest.skip("No PostgreSQL URL")
    factory = _pg_session_factory()
    yield factory
    engine = factory.kw["bind"]
    Base.metadata.drop_all(engine)
    engine.dispose()


# ── resolve_database_url ──────────────────────────────────────────


def test_resolve_database_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    url = resolve_database_url()
    assert url == "postgresql://user:pass@host/db"


# ── PostgreSQL-specific tests ─────────────────────────────────────


@SKIP_NO_PG
def test_duration_stats_postgresql_values(pg_factory) -> None:
    now = datetime.now(timezone.utc)
    with pg_factory() as session:
        j1 = Job(type="generate", status="completed")
        j1.started_at = now - timedelta(seconds=10)
        j1.completed_at = now
        j2 = Job(type="generate", status="completed")
        j2.started_at = now - timedelta(seconds=30)
        j2.completed_at = now
        session.add_all([j1, j2])
        session.commit()

    with pg_factory() as session:
        stats = job_duration_stats(session)
    assert stats.min == pytest.approx(10.0, abs=1.0)
    assert stats.max == pytest.approx(30.0, abs=1.0)
    assert stats.avg == pytest.approx(20.0, abs=1.0)


@SKIP_NO_PG
def test_concurrent_job_creation(pg_factory) -> None:
    with pg_factory() as session:
        session.add(User(id="u1", username="testuser", password_hash="x", role="user"))
        session.commit()

    errors: list[Exception] = []
    results: list[str] = []

    def _create_job(thread_id: int) -> None:
        try:
            with pg_factory() as session:
                job = create_job(session, "generate", user_id="u1")
                session.commit()
                results.append(job.id)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_create_job, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errors during concurrent job creation: {errors}"
    assert len(results) == 10
    assert len(set(results)) == 10


@SKIP_NO_PG
def test_concurrent_lora_reconciliation_claims_one_locked_row(
    pg_factory, tmp_path, monkeypatch,
) -> None:
    """PostgreSQL SKIP LOCKED permits exactly one failure audit per LoRA."""
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    with pg_factory() as session:
        session.add(User(id="lora-user", username="lora-user", password_hash="x"))
        session.add(Job(
            id="lora-job", type=JobType.LORA_TRAINING, status=JobStatus.RUNNING,
            started_at=stale, heartbeat_at=stale,
        ))
        session.add(UserLora(
            id="lora-1", user_id="lora-user", name="Lora", slug="lora",
            status=LoraStatus.TRAINING, training_job_id="lora-job",
        ))
        session.commit()

    ctx = AppContext(
        db=pg_factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=b"test",
        redis=None,  # type: ignore[arg-type]
    )
    ctx.audio_dir.mkdir()
    from songmaker_cli.jobs import lora_training

    original_cleanup = lora_training.cleanup_failed_lora
    lock_held = threading.Event()
    release_lock = threading.Event()
    first_call = True

    def hold_first_lora_lock(**kwargs) -> None:
        nonlocal first_call
        if first_call:
            first_call = False
            lock_held.set()
            assert release_lock.wait(timeout=10), "test did not release held LoRA lock"
        original_cleanup(**kwargs)

    monkeypatch.setattr(lora_training, "cleanup_failed_lora", hold_first_lora_lock)

    results: list[int] = []
    errors: list[Exception] = []

    def _reconcile() -> None:
        try:
            results.append(reconcile_crashed_loras(ctx))
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=_reconcile)
    first.start()
    assert lock_held.wait(timeout=10), "first reconciliation did not acquire LoRA lock"

    second_done = threading.Event()

    def _reconcile_second() -> None:
        _reconcile()
        second_done.set()

    second = threading.Thread(target=_reconcile_second)
    second.start()
    try:
        assert second_done.wait(timeout=10), "second reconciliation waited on the locked LoRA"
        assert results == [0]
    finally:
        release_lock.set()

    first.join(timeout=10)
    second.join(timeout=10)

    assert not errors, f"Errors during concurrent LoRA reconciliation: {errors}"
    assert not first.is_alive()
    assert not second.is_alive()
    assert sum(results) == 1
    with pg_factory() as session:
        lora = session.query(UserLora).filter_by(id="lora-1").one()
        audits = session.query(AuditLog).filter_by(resource_id="lora-1").all()
    assert lora.status == LoraStatus.FAILED
    assert len(audits) == 1


@SKIP_NO_PG
def test_concurrent_session_create_and_prune_respects_cap(pg_factory) -> None:
    max_sessions = 3
    thread_count = 10
    user_id = "session-cap-user"
    with pg_factory() as session:
        session.add(User(id=user_id, username="session-cap", password_hash="x", role="user"))
        session.commit()

    errors: list[Exception] = []
    start = threading.Barrier(thread_count)

    def _create_capped_session() -> None:
        try:
            with pg_factory() as session:
                start.wait(timeout=10)
                assert not session.new and not session.dirty and not session.deleted
                session.commit()
                _begin_exclusive(session, _SESSION_CAP_LOCK_ID)
                expires = datetime.now(timezone.utc) + timedelta(hours=1)
                create_session(session, user_id, expires)
                prune_overflow_sessions(session, user_id, max_sessions)
                session.commit()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_create_capped_session) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"Errors during concurrent session cap: {errors}"
    with pg_factory() as session:
        remaining = (
            session.query(UserSession)
            .filter(UserSession.user_id == user_id)
            .all()
        )
        assert len(remaining) == max_sessions


@SKIP_NO_PG
def test_concurrent_first_resource_event_allocations(pg_factory) -> None:
    """A missing cursor plus concurrent first events still allocate exactly once."""
    with pg_factory() as session:
        session.add(User(id="event-user", username="events", password_hash="x", role="user"))
        session.commit()

    errors: list[Exception] = []
    start = threading.Barrier(10)

    def _create_event(number: int) -> None:
        try:
            with pg_factory() as session:
                start.wait(timeout=10)
                create_generation_created_event(
                    session,
                    user_id="event-user",
                    song_id=f"song-{number}",
                    generation_id=f"generation-{number}",
                )
                session.commit()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_create_event, args=(number,)) for number in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"Errors during concurrent allocation: {errors}"
    with pg_factory() as session:
        events = list_resource_events_after(session, "event-user", 0)
        assert [event.sequence for event in events] == list(range(1, 11))
        assert len({event.generation_id for event in events}) == 10
        assert session.query(ResourceEventCursor).count() == 1


@SKIP_NO_PG
def test_resource_event_rollback_is_atomic_on_postgresql(pg_factory) -> None:
    with pg_factory() as session:
        session.add(User(id="rollback-user", username="rollback", password_hash="x"))
        session.flush()
        create_generation_created_event(
            session,
            user_id="rollback-user",
            song_id="song-1",
            generation_id="duplicate-generation",
        )
        session.commit()

    with pg_factory() as session:
        session.add(
            Album(
                id="rollback-album",
                title="Rollback",
                artist="Test",
                created_by="rollback-user",
            )
        )
        session.flush()
        session.add(
            Song(
                id="rollback-song",
                title="Rollback",
                album_id="rollback-album",
            )
        )
        session.flush()
        session.add(
            Generation(
                id="rolled-back-generation",
                song_id="rollback-song",
                generation_number=1,
                mp3_path="rollback/rolled-back-generation.mp3",
            )
        )
        session.flush()
        with pytest.raises(IntegrityError):
            create_generation_created_event(
                session,
                user_id="rollback-user",
                song_id="song-2",
                generation_id="duplicate-generation",
            )
        session.rollback()

    with pg_factory() as session:
        assert session.get(Generation, "rolled-back-generation") is None
        assert get_resource_event_high_water_mark(session, "rollback-user") == 1
        event = create_generation_created_event(
            session,
            user_id="rollback-user",
            song_id="song-3",
            generation_id="generation-3",
        )
        session.commit()
        assert event.sequence == 2


@SKIP_NO_PG
def test_resource_event_retention_gap_on_postgresql(pg_factory) -> None:
    now = datetime.now(timezone.utc)
    with pg_factory() as session:
        session.add(User(id="retention-user", username="retention", password_hash="x"))
        session.flush()
        events = [
            create_generation_created_event(
                session,
                user_id="retention-user",
                song_id=f"song-{number}",
                generation_id=f"retained-generation-{number}",
            )
            for number in range(1, 4)
        ]
        events[0].created_at = now - timedelta(days=31)
        events[1].created_at = now - timedelta(days=30, seconds=1)
        session.commit()

    with pg_factory() as session:
        assert delete_resource_events_before(session, now - timedelta(days=30)) == 2
        session.commit()
        assert get_resource_event_high_water_mark(session, "retention-user") == 3
        assert get_oldest_resource_event_sequence(session, "retention-user") == 3


@SKIP_NO_PG
def test_alembic_migrations_on_postgresql() -> None:
    from alembic import command
    from alembic.config import Config

    engine = create_engine(TEST_PG_URL)
    Base.metadata.drop_all(engine)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        conn.commit()
    engine.dispose()

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_PG_URL)
    command.upgrade(cfg, "202b0514cdde")

    now = datetime.now(timezone.utc)
    engine = create_engine(TEST_PG_URL)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users "
                "(id, username, password_hash, role, is_active, created_at, updated_at) "
                "VALUES (:id, :username, :password_hash, :role, :is_active, :now, :now)",
            ),
            [
                {
                    "id": "migration-user",
                    "username": "migration",
                    "password_hash": "x",
                    "role": "user",
                    "is_active": True,
                    "now": now,
                },
                {
                    "id": "migration-user-without-events",
                    "username": "migration-without-events",
                    "password_hash": "x",
                    "role": "user",
                    "is_active": True,
                    "now": now,
                },
            ],
        )
    engine.dispose()

    # This legacy revision reached the live database before its application
    # code was reverted.  Prove that upgrading from that exact stamp preserves
    # rows it may already contain and backfills users without cursors.
    command.upgrade(cfg, "40a1c2d3e4f5")
    engine = create_engine(TEST_PG_URL)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO user_resource_cursors (user_id, high_water_mark) "
                "VALUES ('migration-user', 2)",
            )
        )
        conn.execute(
            text(
                "INSERT INTO user_resource_events "
                "(id, user_id, sequence, kind, song_id, generation_id, created_at) "
                "VALUES (:id, 'migration-user', :sequence, 'generation.created', "
                ":song_id, :generation_id, :now)",
            ),
            [
                {
                    "id": "legacy-event-1",
                    "sequence": 1,
                    "song_id": "legacy-song-1",
                    "generation_id": "legacy-generation-1",
                    "now": now,
                },
                {
                    "id": "legacy-event-2",
                    "sequence": 2,
                    "song_id": "legacy-song-2",
                    "generation_id": "legacy-generation-2",
                    "now": now,
                },
            ],
        )
    engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(TEST_PG_URL)
    from sqlalchemy import inspect

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    engine.dispose()

    expected = {
        "users",
        "albums",
        "songs",
        "versions",
        "generations",
        "scores",
        "ratings",
        "jobs",
        "user_sessions",
        "login_attempts",
        "audit_log",
        "generation_presets",
        "resource_event_cursors",
        "resource_events",
        "alembic_version",
    }
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"
    assert "user_resource_cursors" not in tables
    assert "user_resource_events" not in tables

    engine = create_engine(TEST_PG_URL)
    with engine.connect() as conn:
        cursors = conn.execute(
            text(
                "SELECT user_id, high_water_mark FROM resource_event_cursors "
                "WHERE user_id LIKE 'migration-user%' ORDER BY user_id",
            )
        ).all()
        events = conn.execute(
            text(
                "SELECT id, sequence, kind, resource_type, resource_id, generation_id "
                "FROM resource_events WHERE user_id = 'migration-user' ORDER BY sequence",
            )
        ).all()
    engine.dispose()
    assert cursors == [
        ("migration-user", 2),
        ("migration-user-without-events", 0),
    ]
    assert events == [
        (
            "legacy-event-1",
            1,
            "generation.created",
            "song",
            "legacy-song-1",
            "legacy-generation-1",
        ),
        (
            "legacy-event-2",
            2,
            "generation.created",
            "song",
            "legacy-song-2",
            "legacy-generation-2",
        ),
    ]
