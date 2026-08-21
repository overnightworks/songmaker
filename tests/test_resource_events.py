"""Durable per-user resource event outbox and SSE stream."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import TEST_SECRET, make_fake_redis
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import (
    LAST_EVENT_ID_INVALID,
    RESOURCE_EVENT_KIND_GENERATION_CREATED,
    RESOURCE_EVENT_RETENTION_DAYS,
    RESOURCE_EVENT_TYPE_HEARTBEAT,
    RESOURCE_EVENT_TYPE_HELLO,
    RESOURCE_EVENT_TYPE_RESYNC,
    RESOURCE_EVENT_USER_ID_REQUIRED,
)
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import (
    Album,
    Generation,
    Song,
    User,
    UserResourceCursor,
    UserResourceEvent,
    Version,
)
from songmaker_cli.db.queries import (
    create_generation,
    create_user,
    get_oldest_retained_sequence,
    get_user_high_water_mark,
    list_user_events_after,
    purge_expired_resource_events,
    record_generation_created,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user
from songmaker_cli.resource_event_api import (
    _resource_event_generator,
    parse_last_event_id,
)

USER_A = "user-a"
USER_B = "user-b"


def _seed_user_catalog(session: Session, user_id: str, username: str) -> str:
    session.add(User(
        id=user_id, username=username, password_hash="unused", role="user",
    ))
    session.flush()
    album_id = f"album-{user_id}"
    song_id = f"song-{user_id}"
    session.add(Album(
        id=album_id, title=f"Album {username}", artist="A", created_by=user_id,
    ))
    session.add(Song(id=song_id, title="Track", album_id=album_id, track_number=1))
    session.add(Version(
        id=f"ver-{user_id}", song_id=song_id, version_number=1,
        lyrics="la", prompt="rock",
    ))
    session.flush()
    return song_id


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    factory = init_db(tmp_path / "test.db")
    session = factory()
    yield session
    session.close()


@pytest.fixture()
def catalog_session(db_session: Session) -> Session:
    _seed_user_catalog(db_session, USER_A, "alice")
    _seed_user_catalog(db_session, USER_B, "bob")
    db_session.commit()
    return db_session


def _persist_take(session: Session, user_id: str, song_id: str) -> tuple[str, int]:
    gen = create_generation(
        session, song_id=song_id, version_id=None,
        mp3_path=f"{user_id}/take.mp3", model_mode="sft",
    )
    event = record_generation_created(
        session, user_id=user_id, song_id=song_id, generation_id=gen.id,
    )
    return gen.id, event.sequence


def _parse_sse_chunk(chunk: str) -> dict:
    current: dict = {}
    for line in chunk.splitlines():
        if line.startswith("id: "):
            current["id"] = line[4:]
        elif line.startswith("event: "):
            current["event"] = line[7:]
        elif line.startswith("data: "):
            current["data"] = json.loads(line[6:])
    return current


def _consume_frames(
    ctx: AppContext,
    user_id: str,
    last_event_id: int | None,
    count: int,
) -> list[dict]:
    with ctx.db() as session:
        high_water_mark = get_user_high_water_mark(session, user_id)
        oldest = get_oldest_retained_sequence(session, user_id)

    async def _run() -> list[dict]:
        agen = _resource_event_generator(
            ctx, user_id, last_event_id, high_water_mark, oldest,
        )
        frames: list[dict] = []
        try:
            for _ in range(count):
                chunk = await asyncio.wait_for(anext(agen), timeout=2)
                frames.append(_parse_sse_chunk(chunk))
        finally:
            await agen.aclose()
        return frames

    return asyncio.run(_run())


def _make_stream_client(
    tmp_path: Path, user_id: str, factory: sessionmaker[Session] | None = None,
) -> tuple[TestClient, sessionmaker[Session]]:
    if factory is None:
        factory = init_db(tmp_path / "test.db")
        with factory() as session:
            _seed_user_catalog(session, USER_A, "alice")
            _seed_user_catalog(session, USER_B, "bob")
            session.commit()
    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    user = AuthenticatedUser(
        id=user_id, username=f"user-{user_id}", role="user", is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.include_router(router)
    return TestClient(app), factory


def test_parse_last_event_id_missing_and_decimal() -> None:
    assert parse_last_event_id(None) is None
    assert parse_last_event_id("") is None
    assert parse_last_event_id("0") == 0
    assert parse_last_event_id("12") == 12


def test_parse_last_event_id_rejects_non_decimal() -> None:
    with pytest.raises(HTTPException) as exc:
        parse_last_event_id("12a")
    assert exc.value.status_code == 400
    assert exc.value.detail == LAST_EVENT_ID_INVALID


def test_record_requires_user_id(catalog_session: Session) -> None:
    with pytest.raises(ValueError, match=RESOURCE_EVENT_USER_ID_REQUIRED):
        record_generation_created(
            catalog_session, user_id="", song_id="song-user-a", generation_id="g1",
        )


def test_commit_writes_generation_and_exactly_one_event(catalog_session: Session) -> None:
    gen_id, sequence = _persist_take(catalog_session, USER_A, "song-user-a")
    catalog_session.commit()

    events = list_user_events_after(catalog_session, USER_A, 0)
    assert len(events) == 1
    assert events[0].sequence == sequence == 1
    assert events[0].generation_id == gen_id
    assert events[0].song_id == "song-user-a"
    assert events[0].kind == RESOURCE_EVENT_KIND_GENERATION_CREATED
    assert events[0].user_id == USER_A
    assert get_user_high_water_mark(catalog_session, USER_A) == 1
    assert catalog_session.query(Generation).filter_by(id=gen_id).one()


def test_rollback_drops_generation_and_event(catalog_session: Session) -> None:
    _persist_take(catalog_session, USER_A, "song-user-a")
    catalog_session.rollback()

    assert list_user_events_after(catalog_session, USER_A, 0) == []
    assert get_user_high_water_mark(catalog_session, USER_A) == 0
    assert catalog_session.query(UserResourceCursor).filter_by(user_id=USER_A).first() is None
    assert catalog_session.query(Generation).filter_by(song_id="song-user-a").count() == 0


def test_parallel_jobs_get_strictly_increasing_sequences(
    catalog_session: Session,
) -> None:
    factory = sessionmaker(bind=catalog_session.bind)
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker(generation_id: str) -> None:
        try:
            with factory() as session:
                barrier.wait(timeout=5)
                record_generation_created(
                    session,
                    user_id=USER_A,
                    song_id="song-user-a",
                    generation_id=generation_id,
                )
                session.commit()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(f"gen-{index}",))
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    sequences = [
        event.sequence for event in list_user_events_after(catalog_session, USER_A, 0)
    ]
    assert sequences == [1, 2]
    assert get_user_high_water_mark(catalog_session, USER_A) == 2


def test_user_b_cannot_read_user_a_events(catalog_session: Session) -> None:
    gen_id, _ = _persist_take(catalog_session, USER_A, "song-user-a")
    catalog_session.commit()

    assert list_user_events_after(catalog_session, USER_B, 0) == []
    assert get_user_high_water_mark(catalog_session, USER_B) == 0
    leaked = (
        catalog_session.query(UserResourceEvent)
        .filter_by(user_id=USER_B, generation_id=gen_id)
        .first()
    )
    assert leaked is None


def test_purge_keeps_high_water_mark(catalog_session: Session) -> None:
    _persist_take(catalog_session, USER_A, "song-user-a")
    catalog_session.commit()
    event = catalog_session.query(UserResourceEvent).filter_by(user_id=USER_A).one()
    event.created_at = datetime.now(timezone.utc) - timedelta(
        days=RESOURCE_EVENT_RETENTION_DAYS + 1,
    )
    catalog_session.commit()

    deleted = purge_expired_resource_events(catalog_session)
    catalog_session.commit()
    assert deleted == 1
    assert list_user_events_after(catalog_session, USER_A, 0) == []
    assert get_user_high_water_mark(catalog_session, USER_A) == 1


def test_stream_requires_auth(tmp_path: Path) -> None:
    from songmaker_cli.api import router

    factory = init_db(tmp_path / "test.db")
    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    app = FastAPI()
    app.state.ctx = ctx
    app.include_router(router)
    resp = TestClient(app).get("/api/resource-events/stream")
    assert resp.status_code in (401, 403)


def test_stream_http_headers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _finite_stream(*_args, **_kwargs):
        yield 'event: hello\ndata: {"type":"hello","high_water_mark":0}\n\n'

    monkeypatch.setattr(
        "songmaker_cli.resource_event_api._resource_event_generator",
        _finite_stream,
    )
    client, _ = _make_stream_client(tmp_path, USER_A)
    resp = client.get("/api/resource-events/stream")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"


def test_stream_hello_starts_at_high_water_mark(tmp_path: Path) -> None:
    client, factory = _make_stream_client(tmp_path, USER_A)
    with factory() as session:
        _persist_take(session, USER_A, "song-user-a")
        session.commit()
    frames = _consume_frames(client.app.state.ctx, USER_A, None, 1)
    assert frames[0]["event"] == RESOURCE_EVENT_TYPE_HELLO
    assert frames[0]["data"]["high_water_mark"] == 1
    assert "id" not in frames[0]


def test_stream_does_not_replay_without_last_event_id(tmp_path: Path) -> None:
    client, factory = _make_stream_client(tmp_path, USER_A)
    with factory() as session:
        _persist_take(session, USER_A, "song-user-a")
        session.commit()
    frames = _consume_frames(client.app.state.ctx, USER_A, None, 1)
    assert frames[0]["event"] == RESOURCE_EVENT_TYPE_HELLO
    assert all(frame["event"] != RESOURCE_EVENT_KIND_GENERATION_CREATED for frame in frames)


def test_stream_replays_after_last_event_id(tmp_path: Path) -> None:
    client, factory = _make_stream_client(tmp_path, USER_A)
    with factory() as session:
        first_id, _ = _persist_take(session, USER_A, "song-user-a")
        second_id, _ = _persist_take(session, USER_A, "song-user-a")
        session.commit()
    frames = _consume_frames(client.app.state.ctx, USER_A, 1, 2)
    assert frames[0]["event"] == RESOURCE_EVENT_TYPE_HELLO
    created = frames[1]
    assert created["event"] == RESOURCE_EVENT_KIND_GENERATION_CREATED
    assert created["id"] == "2"
    assert created["data"]["generation_id"] == second_id
    assert created["data"]["song_id"] == "song-user-a"
    assert created["data"]["sequence"] == 2
    assert created["data"]["generation_id"] != first_id


def test_stream_duplicate_delivery_is_same_sequence(tmp_path: Path) -> None:
    client, factory = _make_stream_client(tmp_path, USER_A)
    with factory() as session:
        gen_id, _ = _persist_take(session, USER_A, "song-user-a")
        session.commit()
    payloads = []
    for _ in range(2):
        frames = _consume_frames(client.app.state.ctx, USER_A, 0, 2)
        created = next(
            frame for frame in frames
            if frame["event"] == RESOURCE_EVENT_KIND_GENERATION_CREATED
        )
        payloads.append(created["data"]["generation_id"])
        assert created["id"] == "1"
    assert payloads == [gen_id, gen_id]


def test_stream_resync_when_last_event_id_purged(tmp_path: Path) -> None:
    client, factory = _make_stream_client(tmp_path, USER_A)
    with factory() as session:
        _persist_take(session, USER_A, "song-user-a")
        _persist_take(session, USER_A, "song-user-a")
        session.commit()
        for event in session.query(UserResourceEvent).filter_by(user_id=USER_A):
            event.created_at = datetime.now(timezone.utc) - timedelta(
                days=RESOURCE_EVENT_RETENTION_DAYS + 1,
            )
        session.commit()
        purge_expired_resource_events(session)
        session.commit()
        assert get_user_high_water_mark(session, USER_A) == 2
    frames = _consume_frames(client.app.state.ctx, USER_A, 1, 2)
    assert frames[0]["event"] == RESOURCE_EVENT_TYPE_HELLO
    assert frames[0]["data"]["high_water_mark"] == 2
    assert frames[1]["event"] == RESOURCE_EVENT_TYPE_RESYNC
    assert frames[1]["data"]["high_water_mark"] == 2
    assert frames[1]["id"] == "2"


def test_stream_isolates_users(tmp_path: Path) -> None:
    client_a, factory = _make_stream_client(tmp_path, USER_A)
    with factory() as session:
        gen_id, _ = _persist_take(session, USER_A, "song-user-a")
        session.commit()
    frames_b = _consume_frames(client_a.app.state.ctx, USER_B, None, 1)
    dumped = json.dumps(frames_b)
    assert gen_id not in dumped
    assert USER_A not in dumped
    assert "song-user-a" not in dumped
    assert frames_b[0]["data"]["high_water_mark"] == 0
    frames_a = _consume_frames(client_a.app.state.ctx, USER_A, 0, 2)
    created = next(
        frame for frame in frames_a
        if frame["event"] == RESOURCE_EVENT_KIND_GENERATION_CREATED
    )
    assert created["data"]["generation_id"] == gen_id
    assert created["data"]["user_id"] == USER_A


def test_stream_invalid_last_event_id(tmp_path: Path) -> None:
    client, _ = _make_stream_client(tmp_path, USER_A)
    resp = client.get(
        "/api/resource-events/stream", headers={"Last-Event-ID": "nope"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == LAST_EVENT_ID_INVALID


def test_stream_live_event_after_hello(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "songmaker_cli.resource_event_api.RESOURCE_EVENT_POLL_SECONDS", 0.05,
    )
    client, factory = _make_stream_client(tmp_path, USER_A)
    ctx = client.app.state.ctx
    gen_holder: dict[str, str] = {}

    async def _run() -> list[dict]:
        agen = _resource_event_generator(ctx, USER_A, None, 0, None)
        frames: list[dict] = []
        try:
            frames.append(_parse_sse_chunk(await asyncio.wait_for(anext(agen), 1)))
            with factory() as session:
                gen_id, _ = _persist_take(session, USER_A, "song-user-a")
                session.commit()
                gen_holder["id"] = gen_id
            frames.append(_parse_sse_chunk(await asyncio.wait_for(anext(agen), 2)))
        finally:
            await agen.aclose()
        return frames

    frames = asyncio.run(_run())
    assert frames[0]["event"] == RESOURCE_EVENT_TYPE_HELLO
    assert frames[1]["event"] == RESOURCE_EVENT_KIND_GENERATION_CREATED
    assert frames[1]["data"]["generation_id"] == gen_holder["id"]
    assert frames[1]["id"] == "1"


def test_stream_heartbeat_has_no_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "songmaker_cli.resource_event_api.RESOURCE_EVENT_POLL_SECONDS", 0.05,
    )
    monkeypatch.setattr(
        "songmaker_cli.resource_event_api.RESOURCE_EVENT_HEARTBEAT_SECONDS", 0.05,
    )
    client, _ = _make_stream_client(tmp_path, USER_A)
    frames = _consume_frames(client.app.state.ctx, USER_A, None, 2)
    assert frames[0]["event"] == RESOURCE_EVENT_TYPE_HELLO
    heartbeat = frames[1]
    assert heartbeat["event"] == RESOURCE_EVENT_TYPE_HEARTBEAT
    assert "id" not in heartbeat
    assert "sequence" not in heartbeat["data"]


def test_create_user_helper_still_works_for_event_owner(db_session: Session) -> None:
    user = create_user(db_session, "carol", "hash")
    db_session.flush()
    album = Album(id="c-alb", title="C", artist="C", created_by=user.id)
    db_session.add(album)
    db_session.add(Song(id="c-song", title="S", album_id="c-alb", track_number=1))
    db_session.flush()
    gen_id, sequence = _persist_take(db_session, user.id, "c-song")
    db_session.commit()
    assert sequence == 1
    assert gen_id
