"""PostgreSQL contracts; shared pg_factory skips without TEST_DATABASE_URL."""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from functools import partial

import pytest
from sqlalchemy import create_engine, event, insert, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from support.web_app import make_authenticated_user, seed_user

import songmaker_cli.db.queries.jobs as job_queries
from songmaker_cli.api_helpers import _USER_MANAGEMENT_LOCK_ID, _begin_exclusive
from songmaker_cli.api_models import UserLoraCreateRequest
from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import PAGE_MAX_LIMIT, JobStatus, JobType, LoraStatus, SongWorkKind
from songmaker_cli.db.engine import (
    resolve_database_url,
)
from songmaker_cli.db.models import (
    Album,
    AuditLog,
    Base,
    ChatMessage,
    Conversation,
    Generation,
    Job,
    Playlist,
    PlaylistEntry,
    ResourceEventCursor,
    Song,
    User,
    UserLora,
    UserSession,
    UserSongWork,
)
from songmaker_cli.db.queries.activity import (
    list_place_listens,
    list_worked_songs,
    record_song_edit,
    record_song_played,
)
from songmaker_cli.db.queries.auth import create_session, prune_overflow_sessions
from songmaker_cli.db.queries.jobs import (
    JobStatusUpdate,
    create_job,
    job_duration_stats,
    recover_stale_jobs_by_age_and_type,
    update_job_heartbeat,
    update_job_status,
)
from songmaker_cli.db.queries.resource_events import (
    create_generation_created_event,
    delete_resource_events_before,
    get_oldest_resource_event_sequence,
    get_resource_event_high_water_mark,
    list_resource_events_after,
)
from songmaker_cli.db.queries.songs import record_playlist_listen
from songmaker_cli.lifecycle import reconcile_crashed_loras
from songmaker_cli.lora_api import api_create_lora
from songmaker_cli.settings import get_settings

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
SKIP_NO_PG = pytest.mark.skipif(
    not TEST_PG_URL.startswith("postgresql"),
    reason="TEST_DATABASE_URL not set to a PostgreSQL URL",
)


def test_resolve_database_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    url = resolve_database_url()
    assert url == "postgresql://user:pass@host/db"


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
def test_an_admins_own_records_round_trip_into_listen_and_write_on_postgresql(
    pg_factory,
) -> None:
    long_ago = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pg_factory() as session:
        session.add_all([
            User(id="owner", username="leonardo", role="user"),
            User(id="admin", username="felix", role="admin"),
        ])
        session.flush()
        session.add(Album(id="vernissage", title="Vernissage", artist="L", created_by="owner"))
        session.add_all([
            Song(id="first", title="First", album_id="vernissage", slug="first", track_number=1),
            Song(id="second", title="Second", album_id="vernissage", slug="second", track_number=2),
        ])
        session.add(Playlist(id="mix", title="Mix", slug="mix", created_by="admin"))
        session.flush()
        session.add(Generation(
            id="take", song_id="second", generation_number=1, mp3_path="take.mp3",
            created_by="admin", created_at=long_ago,
        ))
        session.add(UserSongWork(user_id="admin", song_id="first", edited_at=long_ago))
        session.flush()
        session.add(PlaylistEntry(playlist_id="mix", generation_id="take", position=0))
        session.commit()

    for record_work in (
        lambda session: record_playlist_listen(
            session, session.get(Playlist, "mix"), song=session.get(Song, "second"),
        ),
        partial(record_song_played, user_id="admin", song_id="second", in_playlist=True),
        partial(record_song_edit, user_id="admin", song_id="second", kind=SongWorkKind.LYRICS),
        partial(record_song_played, user_id="admin", song_id="second", in_playlist=False),
    ):
        with pg_factory() as session:
            record_work(session)
            session.commit()

    with pg_factory() as session:
        row = session.get(UserSongWork, ("admin", "second"))
        mix_played_at = session.get(Playlist, "mix").last_played_at
        listens = [
            (listen.place.id, listen.played_at, listen.song.id, listen.song_number)
            for listen in list_place_listens(
                session, viewer_id="admin", owner_id=None, limit=PAGE_MAX_LIMIT,
            )
        ]
        works = [
            (worked.song.id, worked.work, worked.worked_at)
            for worked in list_worked_songs(session, viewer_id="admin", owner_id=None, limit=3)
        ]
        owners_lists = (
            list_place_listens(session, viewer_id="owner", owner_id="owner", limit=PAGE_MAX_LIMIT),
            list_worked_songs(session, viewer_id="owner", owner_id="owner", limit=3),
        )

    assert listens == [
        ("vernissage", row.album_played_at, "second", 2),
        ("mix", mix_played_at, "second", 1),
    ]
    assert works == [
        ("second", SongWorkKind.LYRICS, row.edited_at),
        ("first", SongWorkKind.EDITED, long_ago),
    ]
    assert owners_lists == ([], [])


HOME_LIST_STATEMENT_BUDGET_MS = 100.0


def _seed_libraries_of_many_musicians(
    session: Session, *, musicians: int, albums: int, songs: int,
) -> None:
    """Every musician owns ``albums`` albums of ``songs`` songs and has worked on and
    listened to each song; playlist ``p<a>`` holds album ``a``'s takes, played from its first.
    """
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    owners = [f"m{m}" for m in range(musicians)]
    session.add_all([
        User(id=owner, username=owner, role="user") for owner in owners
    ])
    session.flush()
    session.add_all([Conversation(id=f"{owner}-c", user_id=owner) for owner in owners])
    session.execute(insert(Album), [
        {"id": f"{owner}-a{a}", "title": f"{owner}-a{a}", "artist": "A", "created_by": owner}
        for owner in owners for a in range(albums)
    ])
    song_rows = [
        (owner, a, s, start + timedelta(seconds=index))
        for index, (owner, a, s) in enumerate(
            (owner, a, s) for owner in owners for a in range(albums) for s in range(songs)
        )
    ]
    session.execute(insert(Song), [
        {"id": f"{owner}-a{a}-s{s}", "title": f"s{s}", "album_id": f"{owner}-a{a}",
         "slug": f"s{s}", "track_number": s}
        for owner, a, s, _at in song_rows
    ])
    session.execute(insert(Playlist), [
        {"id": f"{owner}-p{a}", "title": f"{owner}-p{a}", "slug": f"{owner}-p{a}",
         "created_by": owner, "last_played_at": start + timedelta(seconds=a),
         "last_played_song_id": f"{owner}-a{a}-s0"}
        for owner in owners for a in range(albums)
    ])
    session.execute(insert(Generation), [
        {"id": f"{owner}-a{a}-s{s}-g", "song_id": f"{owner}-a{a}-s{s}", "generation_number": 1,
         "mp3_path": f"{owner}-a{a}-s{s}.mp3", "created_by": owner, "created_at": at}
        for owner, a, s, at in song_rows
    ])
    session.execute(insert(PlaylistEntry), [
        {"playlist_id": f"{owner}-p{a}", "generation_id": f"{owner}-a{a}-s{s}-g", "position": s}
        for owner, a, s, _at in song_rows
    ])
    session.execute(insert(UserSongWork), [
        {"user_id": owner, "song_id": f"{owner}-a{a}-s{s}", "edited_at": at,
         "edit_kind": SongWorkKind.LYRICS, "album_played_at": at}
        for owner, a, s, at in song_rows
    ])
    session.execute(insert(ChatMessage), [
        {"conversation_id": f"{owner}-c", "song_id": f"{owner}-a{a}-s{s}", "role": role,
         "content": "Tighten the chorus", "created_at": at}
        for owner, a, s, at in song_rows for role in ("user", "assistant")
    ])


@SKIP_NO_PG
def test_home_lists_run_within_budget_on_a_busy_library_on_postgresql(pg_factory) -> None:
    with pg_factory() as session:
        _seed_libraries_of_many_musicians(session, musicians=5, albums=20, songs=10)
        session.commit()
        session.execute(text("ANALYZE"))

    with pg_factory() as session:
        statements: list[tuple[str, dict]] = []

        def record(conn, cursor, statement, parameters, context, executemany) -> None:
            statements.append((statement, parameters))

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            listens = list_place_listens(
                session, viewer_id="m0", owner_id="m0", limit=PAGE_MAX_LIMIT,
            )
            worked_songs = list_worked_songs(session, viewer_id="m0", owner_id="m0", limit=3)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        timings = [
            session.connection().exec_driver_sql(
                f"EXPLAIN (ANALYZE, FORMAT JSON) {statement}", parameters,
            ).scalar_one()[0]["Execution Time"]
            for statement, parameters in statements
        ]

    print(f"Home list statements on PostgreSQL, execution ms: {timings}")
    assert len(listens) == 40
    assert [worked.song.id for worked in worked_songs] == ["m0-a19-s9", "m0-a19-s8", "m0-a19-s7"]
    assert len(timings) == 4
    assert max(timings) < HOME_LIST_STATEMENT_BUDGET_MS


@SKIP_NO_PG
def test_concurrent_job_creation(pg_factory) -> None:
    with pg_factory() as session:
        session.add(User(id="u1", username="testuser", role="user"))
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
def test_concurrent_lora_creation_admits_only_one_at_voice_limit(
    pg_factory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The advisory lock admits one of two simultaneous creates at the limit.

    The session lock timeout turns a missed lock release into a test failure,
    rather than an indefinitely blocked CI worker.
    """
    monkeypatch.setenv("MAX_USER_LORAS", "1")
    get_settings.cache_clear()
    with pg_factory() as session:
        session.add(User(id="lora-user", username="lora-user"))
        session.commit()

    barrier = threading.Barrier(2)
    statuses: list[int] = []
    errors: list[Exception] = []
    user = make_authenticated_user("lora-user")

    def create(name: str) -> None:
        try:
            with pg_factory() as session:
                session.execute(text("SET lock_timeout = '10s'"))
                session.commit()
                barrier.wait(timeout=10)
                result = api_create_lora(UserLoraCreateRequest(name=name), user, session)
                statuses.append(result.status_code if hasattr(result, "status_code") else 200)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=create, args=(name,)) for name in ("First", "Second")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert not errors, f"Errors during concurrent LoRA creation: {errors}"
    assert sorted(statuses) == [200, 409]
    with pg_factory() as session:
        assert session.query(UserLora).filter(UserLora.deleted_at.is_(None)).count() == 1


@SKIP_NO_PG
def test_stale_job_reaper_does_not_overwrite_fresh_heartbeat(pg_factory, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    with pg_factory() as session:
        job = create_job(session, JobType.GENERATE)
        update_job_status(session, job.id, JobStatusUpdate(JobStatus.RUNNING))
        job.heartbeat_at = now - timedelta(hours=1)
        session.commit()
        job_id = job.id

    reaper_read = threading.Event()
    heartbeat_written = threading.Event()
    errors: list[Exception] = []
    results: list[dict[str, int]] = []

    def pause_before_update(candidate: Job) -> None:
        if candidate.id != job_id:
            return
        reaper_read.set()
        assert heartbeat_written.wait(timeout=10), "heartbeat did not finish"

    monkeypatch.setattr(job_queries, "_before_stale_job_recovery_update", pause_before_update)

    def reap() -> None:
        try:
            with pg_factory() as session:
                results.append(recover_stale_jobs_by_age_and_type(session, now=now))
                session.commit()
        except Exception as exc:
            errors.append(exc)

    def heartbeat() -> None:
        try:
            if not reaper_read.wait(timeout=10):
                raise RuntimeError("reaper did not read the job")
            with pg_factory() as session:
                update_job_heartbeat(session, job_id)
                session.commit()
        except Exception as exc:
            errors.append(exc)
        finally:
            heartbeat_written.set()

    reaper = threading.Thread(target=reap)
    heartbeater = threading.Thread(target=heartbeat)
    reaper.start()
    heartbeater.start()
    reaper.join(timeout=10)
    heartbeater.join(timeout=10)

    assert not reaper.is_alive()
    assert not heartbeater.is_alive()
    assert not errors, f"Errors during stale-job reaping: {errors}"
    assert results == [{}]
    with pg_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.RUNNING
        assert job.heartbeat_at is not None
        assert job.heartbeat_at > now - timedelta(minutes=1)


@SKIP_NO_PG
def test_concurrent_lora_reconciliation_claims_one_locked_row(
    pg_factory, tmp_path, monkeypatch,
) -> None:
    """PostgreSQL SKIP LOCKED permits exactly one failure audit per LoRA."""
    terminalized_at = datetime.now(timezone.utc)
    with pg_factory() as session:
        session.add(User(id="lora-user", username="lora-user"))
        session.add(Job(
            id="lora-job", type=JobType.LORA_TRAINING, status=JobStatus.FAILED,
            completed_at=terminalized_at,
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
        signing_key=b"test",
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
        if not second_done.wait(timeout=10):
            raise RuntimeError("second reconciliation waited on the locked LoRA")
        if results != [0]:
            raise RuntimeError(f"unexpected reconciliation results: {results}")
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
@pytest.mark.parametrize("first_operation", ["renew", "revoke"])
def test_session_revocation_wins_over_concurrent_renewal(pg_factory, first_operation) -> None:
    """defect:#1590: either lock order ends with revocation, never resurrection."""
    from concurrent.futures import ThreadPoolExecutor

    from songmaker_cli.auth_stores import DatabaseSessionRecordStore

    now = datetime.now(timezone.utc)
    with pg_factory() as db:
        user = seed_user(db, "renew-revoke")
        record = create_session(db, user.id, now + timedelta(hours=1))
        db.commit()
        session_id = record.id
        db.expunge(record)

    competing_statement = threading.Event()

    def compete():
        with pg_factory() as db:
            db.execute(text("SET lock_timeout = '5s'"))
            store = DatabaseSessionRecordStore(db)

            def statement_started(conn, cursor, statement, parameters, context, executemany):
                if context.isupdate or context.isdelete:
                    competing_statement.set()

            event.listen(db.connection(), "before_cursor_execute", statement_started)
            if first_operation == "renew":
                store.delete(session_id)
                result = None
            else:
                result = store.touch(session_id, expires_at=now + timedelta(hours=2))
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=1) as executor, pg_factory() as db:
        store = DatabaseSessionRecordStore(db)
        if first_operation == "renew":
            assert store.touch(session_id, expires_at=now + timedelta(hours=2)) is True
        else:
            store.delete(session_id)
        future = executor.submit(compete)
        try:
            assert competing_statement.wait(timeout=5), "Competing statement never started"
            db.commit()
        finally:
            db.rollback()
        result = future.result(timeout=10)
        if first_operation == "revoke":
            assert result is False

    with pg_factory() as db:
        assert db.get(UserSession, session_id) is None


@SKIP_NO_PG
def test_concurrent_session_create_and_prune_respects_cap(pg_factory) -> None:
    max_sessions = 3
    thread_count = 10
    user_id = "session-cap-user"
    with pg_factory() as session:
        session.add(User(id=user_id, username="session-cap", role="user"))
        session.commit()

    errors: list[Exception] = []
    start = threading.Barrier(thread_count)

    def _create_capped_session() -> None:
        try:
            with pg_factory() as session:
                start.wait(timeout=10)
                if session.new or session.dirty or session.deleted:
                    raise RuntimeError("session unexpectedly has pending changes")
                session.commit()
                _begin_exclusive(session, _USER_MANAGEMENT_LOCK_ID)
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
        session.add(User(id="event-user", username="events", role="user"))
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
        session.add(User(id="rollback-user", username="rollback"))
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
        session.add(User(id="retention-user", username="retention"))
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
