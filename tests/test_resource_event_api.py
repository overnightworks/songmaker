"""Contract tests for the replayable authenticated resource-event stream."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import TEST_SECRET, make_fake_redis, make_test_app
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event as sqlalchemy_event

import songmaker_cli.resource_event_api as resource_api
from songmaker_cli.api_models import (
    GenerationCreatedResourceEvent,
    ResourceHelloEvent,
)
from songmaker_cli.auth import sign_session_id
from songmaker_cli.constants import (
    LAST_EVENT_ID_INVALID,
    POSTGRES_BIGINT_MAX,
    REDIS_RESOURCE_STREAM_LEASE_GLOBAL_KEY,
    REDIS_RESOURCE_STREAM_LEASE_USER_PREFIX,
    RESOURCE_EVENT_STREAM_CAPACITY_UNAVAILABLE,
    RESOURCE_EVENT_STREAM_CONNECTION_SECONDS,
    RESOURCE_EVENT_STREAM_OPEN_LIMIT,
    ResourceEventKind,
)
from songmaker_cli.db.models import Job, ResourceEvent, ResourceEventCursor, User
from songmaker_cli.db.queries import (
    create_generation_created_event,
    create_session,
    create_user,
    list_resource_events_after,
)
from songmaker_cli.middleware import SESSION_COOKIE, ResourceStreamDeadlineMiddleware
from songmaker_cli.redis_client import RedisConcurrentLeaseLimiter


def _seed_stream_users(session) -> None:
    create_user(session, "alice", "hash", role="user")
    create_user(session, "bob", "hash", role="user")
    create_user(session, "admin", "hash", role="admin")


def _authenticated_clients(tmp_path: Path):
    base_client, factory = make_test_app(tmp_path, seed_db=_seed_stream_users)
    clients: dict[str, TestClient] = {}
    user_ids: dict[str, str] = {}
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    with factory() as session:
        for username in ("alice", "bob", "admin"):
            user = session.query(User).filter_by(username=username).one()
            user_ids[username] = user.id
            user_session = create_session(session, user.id, expires_at)
            session.flush()
            client = (
                base_client
                if username == "alice"
                else TestClient(
                    base_client.app,
                    cookies={},
                )
            )
            client.cookies.set(
                SESSION_COOKIE,
                sign_session_id(user_session.id, TEST_SECRET),
            )
            clients[username] = client
        session.commit()
    return clients, factory, user_ids


def _create_event(factory, user_id: str, number: int) -> str:
    generation_id = f"generation-{number}"
    with factory() as session:
        create_generation_created_event(
            session,
            user_id=user_id,
            song_id=f"song-{number}",
            generation_id=generation_id,
        )
        session.commit()
    return generation_id


def _parse_sse(chunk: str) -> dict:
    if chunk.startswith(":"):
        return {"comment": chunk.removeprefix(":").strip()}
    parsed: dict[str, object] = {}
    for line in chunk.strip().splitlines():
        field, _, value = line.partition(":")
        value = value.lstrip()
        if field == "data":
            parsed[field] = json.loads(value)
        else:
            parsed[field] = value
    return parsed


async def _take_frames(generator, count: int) -> list[dict]:
    frames = []
    try:
        for _ in range(count):
            frames.append(_parse_sse(await anext(generator)))
    finally:
        await generator.aclose()
    return frames


def _collect(generator, count: int) -> list[dict]:
    return asyncio.run(_take_frames(generator, count))


def _install_finite_route_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _finite(
        _ctx,
        _user_id,
        _last_event_id,
        high_water_mark,
        _oldest_retained,
    ):
        yield resource_api.format_sse(
            "hello",
            ResourceHelloEvent.from_high_water_mark(high_water_mark),
            event_id=high_water_mark,
        )

    monkeypatch.setattr(resource_api, "_resource_event_generator", _finite)


@pytest.mark.parametrize("raw", ["-1", "nope", "+1", " 1", "1 ", "١"])
def test_parse_last_event_id_rejects_non_ascii_non_negative_decimal(raw: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        resource_api.parse_last_event_id(raw)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == LAST_EVENT_ID_INVALID


def test_parse_last_event_id_handles_empty_leading_zero_and_bigint_ahead() -> None:
    assert resource_api.parse_last_event_id(None) is None
    assert resource_api.parse_last_event_id("") is None
    assert resource_api.parse_last_event_id("00012") == 12
    assert resource_api.parse_last_event_id(str(POSTGRES_BIGINT_MAX)) == POSTGRES_BIGINT_MAX
    assert resource_api.parse_last_event_id(str(POSTGRES_BIGINT_MAX + 1)) == (
        POSTGRES_BIGINT_MAX + 1
    )
    assert resource_api.parse_last_event_id("9" * 10_000) == POSTGRES_BIGINT_MAX + 1


def test_wire_models_preserve_bigint_precision_as_decimal_strings() -> None:
    event = SimpleNamespace(
        sequence=POSTGRES_BIGINT_MAX,
        resource_id="song-max",
        generation_id="generation-max",
        created_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
    )
    payload = GenerationCreatedResourceEvent.from_event(event)
    frame = _parse_sse(
        resource_api.format_sse(
            ResourceEventKind.GENERATION_CREATED,
            payload,
            event_id=POSTGRES_BIGINT_MAX,
        )
    )
    assert frame["id"] == str(POSTGRES_BIGINT_MAX)
    assert frame["data"]["sequence"] == str(POSTGRES_BIGINT_MAX)
    assert isinstance(frame["data"]["sequence"], str)


def test_max_bigint_replay_preserves_cursor_and_sequence_exactly(tmp_path: Path) -> None:
    clients, factory, users = _authenticated_clients(tmp_path)
    _create_event(factory, users["alice"], 1)
    with factory() as session:
        session.query(ResourceEvent).filter_by(user_id=users["alice"]).update(
            {ResourceEvent.sequence: POSTGRES_BIGINT_MAX},
        )
        session.query(ResourceEventCursor).filter_by(user_id=users["alice"]).update(
            {ResourceEventCursor.high_water_mark: POSTGRES_BIGINT_MAX},
        )
        session.commit()

    frames = _collect(
        resource_api._resource_event_generator(
            clients["alice"].app.state.ctx,
            users["alice"],
            POSTGRES_BIGINT_MAX - 1,
            POSTGRES_BIGINT_MAX,
            POSTGRES_BIGINT_MAX,
        ),
        2,
    )
    assert frames[0] == {
        "event": "hello",
        "data": {"high_water_mark": str(POSTGRES_BIGINT_MAX)},
    }
    assert frames[1]["id"] == str(POSTGRES_BIGINT_MAX)
    assert frames[1]["event"] == "generation.created"
    assert frames[1]["data"]["sequence"] == str(POSTGRES_BIGINT_MAX)
    assert frames[1]["data"]["resource_id"] == "song-1"
    assert frames[1]["data"]["generation_id"] == "generation-1"


def test_fresh_stream_hello_owns_cursor_and_skips_history(tmp_path: Path) -> None:
    clients, factory, users = _authenticated_clients(tmp_path)
    _create_event(factory, users["alice"], 1)
    _create_event(factory, users["alice"], 2)
    ctx = clients["alice"].app.state.ctx
    generator = resource_api._resource_event_generator(
        ctx,
        users["alice"],
        None,
        2,
        1,
    )

    async def _run() -> list[dict]:
        frames = [_parse_sse(await anext(generator))]
        _create_event(factory, users["alice"], 3)
        frames.append(_parse_sse(await anext(generator)))
        await generator.aclose()
        return frames

    frames = asyncio.run(_run())
    assert frames[0] == {
        "id": "2",
        "event": "hello",
        "data": {"high_water_mark": "2"},
    }
    assert frames[1]["id"] == "3"
    assert frames[1]["data"]["generation_id"] == "generation-3"


def test_replay_is_ordered_bounded_to_handshake_then_goes_live(tmp_path: Path) -> None:
    clients, factory, users = _authenticated_clients(tmp_path)
    for number in range(1, 4):
        _create_event(factory, users["alice"], number)
    ctx = clients["alice"].app.state.ctx
    frames = _collect(
        resource_api._resource_event_generator(
            ctx,
            users["alice"],
            0,
            2,
            1,
        ),
        4,
    )
    assert frames[0] == {
        "event": "hello",
        "data": {"high_water_mark": "2"},
    }
    assert [frame["id"] for frame in frames[1:]] == ["1", "2", "3"]
    assert [frame["data"]["sequence"] for frame in frames[1:]] == ["1", "2", "3"]
    assert "user_id" not in frames[1]["data"]
    assert "song_id" not in frames[1]["data"]


@pytest.mark.parametrize(
    ("last_event_id", "high_water_mark", "oldest"),
    [
        (1, 2, None),
        (0, 3, 2),
        (POSTGRES_BIGINT_MAX + 1, 3, 1),
    ],
)
def test_handshake_gaps_emit_exactly_one_resync_with_data(
    tmp_path: Path,
    last_event_id: int,
    high_water_mark: int,
    oldest: int | None,
) -> None:
    clients, _, users = _authenticated_clients(tmp_path)
    frames = _collect(
        resource_api._resource_event_generator(
            clients["alice"].app.state.ctx,
            users["alice"],
            last_event_id,
            high_water_mark,
            oldest,
        ),
        2,
    )
    assert frames[0] == {
        "event": "hello",
        "data": {"high_water_mark": str(high_water_mark)},
    }
    assert frames[1] == {
        "id": str(high_water_mark),
        "event": "resync",
        "data": {"high_water_mark": str(high_water_mark)},
    }


def test_gap_resync_advances_to_live_without_a_second_resync(tmp_path: Path) -> None:
    clients, factory, users = _authenticated_clients(tmp_path)
    _create_event(factory, users["alice"], 1)
    _create_event(factory, users["alice"], 2)
    with factory() as session:
        session.query(ResourceEvent).filter_by(
            user_id=users["alice"], sequence=1,
        ).delete()
        session.commit()
    generator = resource_api._resource_event_generator(
        clients["alice"].app.state.ctx,
        users["alice"],
        0,
        2,
        2,
    )

    async def _run() -> list[dict]:
        frames = [
            _parse_sse(await anext(generator)),
            _parse_sse(await anext(generator)),
        ]
        _create_event(factory, users["alice"], 3)
        frames.append(_parse_sse(await anext(generator)))
        await generator.aclose()
        return frames

    frames = asyncio.run(_run())
    assert [frame["event"] for frame in frames] == [
        "hello",
        "resync",
        "generation.created",
    ]
    assert [frame.get("id") for frame in frames] == [None, "2", "3"]


def test_internal_replay_hole_resyncs_before_delivering_later_rows(tmp_path: Path) -> None:
    clients, factory, users = _authenticated_clients(tmp_path)
    for number in range(1, 4):
        _create_event(factory, users["alice"], number)
    with factory() as session:
        session.query(ResourceEvent).filter_by(
            user_id=users["alice"],
            sequence=2,
        ).delete()
        session.commit()

    frames = _collect(
        resource_api._resource_event_generator(
            clients["alice"].app.state.ctx,
            users["alice"],
            0,
            3,
            1,
        ),
        2,
    )
    assert [frame["event"] for frame in frames] == ["hello", "resync"]
    assert frames[1]["id"] == "3"


def test_retention_race_empty_page_resyncs_instead_of_advancing(tmp_path: Path) -> None:
    clients, factory, users = _authenticated_clients(tmp_path)
    _create_event(factory, users["alice"], 1)
    _create_event(factory, users["alice"], 2)
    generator = resource_api._resource_event_generator(
        clients["alice"].app.state.ctx,
        users["alice"],
        0,
        2,
        1,
    )

    async def _run() -> list[dict]:
        hello = _parse_sse(await anext(generator))
        with factory() as session:
            session.query(ResourceEvent).filter_by(user_id=users["alice"]).delete()
            session.commit()
        resync = _parse_sse(await anext(generator))
        await generator.aclose()
        return [hello, resync]

    frames = asyncio.run(_run())
    assert [frame["event"] for frame in frames] == ["hello", "resync"]
    assert frames[1]["id"] == "2"


def test_reconnect_delivery_is_at_least_once(tmp_path: Path) -> None:
    clients, factory, users = _authenticated_clients(tmp_path)
    _create_event(factory, users["alice"], 1)
    ctx = clients["alice"].app.state.ctx
    deliveries = []
    for _ in range(2):
        frames = _collect(
            resource_api._resource_event_generator(
                ctx,
                users["alice"],
                0,
                1,
                1,
            ),
            2,
        )
        deliveries.append(frames[1])
    assert deliveries[0] == deliveries[1]
    assert deliveries[0]["id"] == "1"


def test_heartbeat_is_comment_without_event_id_or_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients, _, users = _authenticated_clients(tmp_path)
    monkeypatch.setattr(resource_api, "RESOURCE_EVENT_STREAM_HEARTBEAT_SECONDS", 0)
    frames = _collect(
        resource_api._resource_event_generator(
            clients["alice"].app.state.ctx,
            users["alice"],
            None,
            0,
            None,
        ),
        2,
    )
    assert frames == [
        {"id": "0", "event": "hello", "data": {"high_water_mark": "0"}},
        {"comment": "heartbeat"},
    ]


def test_connection_stops_at_the_sixty_second_wall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients, _, users = _authenticated_clients(tmp_path)
    ticks = iter([0.0, 60.0, 60.0])
    monkeypatch.setattr(resource_api, "monotonic", lambda: next(ticks))
    assert RESOURCE_EVENT_STREAM_CONNECTION_SECONDS == 60
    generator = resource_api._resource_event_generator(
        clients["alice"].app.state.ctx,
        users["alice"],
        None,
        0,
        None,
    )

    async def _run() -> dict:
        hello = _parse_sse(await anext(generator))
        with pytest.raises(StopAsyncIteration):
            await anext(generator)
        return hello

    assert asyncio.run(_run())["event"] == "hello"


def test_poll_crossing_deadline_does_not_emit_a_late_heartbeat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients, _, users = _authenticated_clients(tmp_path)
    ticks = iter([0.0, 0.0, 0.0, 60.0])
    monkeypatch.setattr(resource_api, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(resource_api, "RESOURCE_EVENT_STREAM_HEARTBEAT_SECONDS", 0)

    async def _poll_crossing_deadline(*_args, **_kwargs):
        return resource_api.ResourceEventPage(high_water_mark=0, events=())

    monkeypatch.setattr(resource_api, "_read_event_page_before", _poll_crossing_deadline)
    generator = resource_api._resource_event_generator(
        clients["alice"].app.state.ctx,
        users["alice"],
        None,
        0,
        None,
    )

    async def _run() -> dict:
        hello = _parse_sse(await anext(generator))
        with pytest.raises(StopAsyncIteration):
            await anext(generator)
        return hello

    assert asyncio.run(_run())["event"] == "hello"


def test_route_requires_auth_and_validates_header_after_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients, _, _ = _authenticated_clients(tmp_path)
    _install_finite_route_stream(monkeypatch)
    unauthenticated = TestClient(clients["alice"].app, cookies={})
    assert unauthenticated.get("/api/resource-events/stream").status_code == 401
    response = clients["alice"].get(
        "/api/resource-events/stream",
        headers={"Last-Event-ID": "-1"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": LAST_EVENT_ID_INVALID}


def test_full_app_preserves_resource_sse_headers_and_other_api_cache_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients, factory, users = _authenticated_clients(tmp_path)
    _install_finite_route_stream(monkeypatch)
    with factory() as session:
        job = Job(type="generate", status="completed", user_id=users["alice"])
        session.add(job)
        session.commit()
        job_id = job.id

    async def _finite_job(*_args, **_kwargs):
        yield 'data: {"status":"completed"}\n\n'

    monkeypatch.setattr(
        "songmaker_cli.generation_api._job_event_generator",
        _finite_job,
    )
    resource_response = clients["alice"].get("/api/resource-events/stream")
    assert resource_response.status_code == 200
    assert resource_response.headers["content-type"].startswith("text/event-stream")
    assert resource_response.headers["cache-control"] == "no-cache, no-store"
    assert resource_response.headers["x-accel-buffering"] == "no"
    assert clients["alice"].get("/api/auth/me").headers["cache-control"] == "no-store"
    job_response = clients["alice"].get(f"/api/jobs/{job_id}/stream")
    assert job_response.headers["cache-control"] == "no-store"


def test_auth_db_connection_is_returned_before_body_iteration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients, factory, _ = _authenticated_clients(tmp_path)
    engine = factory.kw["bind"]
    checked_out = 0
    observed: list[int] = []

    def _checkout(*_args) -> None:
        nonlocal checked_out
        checked_out += 1

    def _checkin(*_args) -> None:
        nonlocal checked_out
        checked_out -= 1

    sqlalchemy_event.listen(engine, "checkout", _checkout)
    sqlalchemy_event.listen(engine, "checkin", _checkin)

    async def _finite(
        _ctx,
        _user_id,
        _last_event_id,
        high_water_mark,
        _oldest_retained,
    ):
        observed.append(checked_out)
        yield resource_api.format_sse(
            "hello",
            ResourceHelloEvent.from_high_water_mark(high_water_mark),
        )

    monkeypatch.setattr(resource_api, "_resource_event_generator", _finite)
    try:
        response = clients["alice"].get("/api/resource-events/stream")
    finally:
        sqlalchemy_event.remove(engine, "checkout", _checkout)
        sqlalchemy_event.remove(engine, "checkin", _checkin)
    assert response.status_code == 200
    assert observed == [0]


def test_each_reconnect_reauthenticates_disabled_account(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients, factory, users = _authenticated_clients(tmp_path)
    _install_finite_route_stream(monkeypatch)
    assert clients["alice"].get("/api/resource-events/stream").status_code == 200
    with factory() as session:
        session.get(User, users["alice"]).is_active = False
        session.commit()
    clients["alice"].app.state.session_cache.delete_user_sessions(users["alice"])
    assert clients["alice"].get("/api/resource-events/stream").status_code == 403


def test_authenticated_stream_isolates_two_users_and_admin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients, factory, users = _authenticated_clients(tmp_path)
    generation_id = _create_event(factory, users["alice"], 1)
    original_generator = resource_api._resource_event_generator
    monkeypatch.setattr(resource_api, "RESOURCE_EVENT_STREAM_POLL_SECONDS", 0.01)

    async def _bounded(*args, **kwargs):
        generator = original_generator(*args, **kwargs)
        try:
            yield await anext(generator)
            try:
                yield await asyncio.wait_for(anext(generator), timeout=0.05)
            except (TimeoutError, StopAsyncIteration):
                return
        finally:
            await generator.aclose()

    monkeypatch.setattr(resource_api, "_resource_event_generator", _bounded)
    bodies = {
        username: client.get(
            "/api/resource-events/stream",
            headers={"Last-Event-ID": "0"},
        ).text
        for username, client in clients.items()
    }
    assert generation_id in bodies["alice"]
    assert "song-1" in bodies["alice"]
    assert generation_id not in bodies["bob"]
    assert generation_id not in bodies["admin"]
    assert all(user_id not in body for body in bodies.values() for user_id in users.values())


def test_event_query_pages_and_rejects_non_positive_limit(tmp_path: Path) -> None:
    _, factory, users = _authenticated_clients(tmp_path)
    for number in range(1, 4):
        _create_event(factory, users["alice"], number)
    with factory() as session:
        page = list_resource_events_after(
            session,
            users["alice"],
            0,
            through=3,
            limit=2,
        )
        assert [event.sequence for event in page] == [1, 2]
        with pytest.raises(ValueError, match="positive"):
            list_resource_events_after(session, users["alice"], 0, limit=0)


def test_concurrent_lease_limiter_enforces_scope_global_release_and_pruning() -> None:
    redis = make_fake_redis()
    limiter = RedisConcurrentLeaseLimiter(
        redis,
        scope_prefix=REDIS_RESOURCE_STREAM_LEASE_USER_PREFIX,
        global_key=REDIS_RESOURCE_STREAM_LEASE_GLOBAL_KEY,
        max_per_scope=2,
        max_global=3,
        lease_seconds=65,
    )
    alice_one = limiter.acquire("alice")
    alice_two = limiter.acquire("alice")
    assert alice_one and alice_two and alice_one != alice_two
    assert limiter.acquire("alice") is None
    bob_one = limiter.acquire("bob")
    assert bob_one
    assert limiter.acquire("carol") is None

    limiter.release("alice", alice_one)
    carol_one = limiter.acquire("carol")
    assert carol_one
    assert (
        redis.zscore(
            f"{REDIS_RESOURCE_STREAM_LEASE_USER_PREFIX}:alice",
            alice_two,
        )
        is not None
    )

    limiter.release("carol", carol_one)
    stale_key = f"{REDIS_RESOURCE_STREAM_LEASE_USER_PREFIX}:dave"
    redis.zadd(stale_key, {"expired-token": 0})
    redis.zadd(REDIS_RESOURCE_STREAM_LEASE_GLOBAL_KEY, {"expired-global": 0})
    dave_one = limiter.acquire("dave")
    assert dave_one
    assert redis.zscore(stale_key, "expired-token") is None
    assert redis.zscore(REDIS_RESOURCE_STREAM_LEASE_GLOBAL_KEY, "expired-global") is None


def test_disconnect_releases_lease_off_loop_and_contains_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    release_started = threading.Event()
    allow_release = threading.Event()
    release_calls: list[tuple[str, str]] = []

    class _SlowFailingLimiter:
        def release(self, user_id: str, token: str) -> None:
            release_calls.append((user_id, token))
            release_started.set()
            allow_release.wait(timeout=1)
            raise ConnectionError("redis unavailable")

    async def _finite_stream(*_args, **_kwargs):
        yield "event: hello\ndata: {}\n\n"

    monkeypatch.setattr(resource_api, "_resource_event_generator", _finite_stream)

    async def _run() -> float:
        generator = resource_api._leased_resource_event_generator(
            SimpleNamespace(),
            _SlowFailingLimiter(),
            "lease-token",
            "alice-id",
            None,
            0,
            None,
        )
        await anext(generator)
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        await generator.aclose()
        close_duration = loop.time() - started_at
        assert await asyncio.to_thread(release_started.wait, 1)
        allow_release.set()
        for _ in range(100):
            if not resource_api._LEASE_RELEASE_TASKS:
                break
            await asyncio.sleep(0.01)
        assert not resource_api._LEASE_RELEASE_TASKS
        return close_duration

    try:
        with caplog.at_level("WARNING", logger=resource_api.__name__):
            close_duration = asyncio.run(_run())
    finally:
        allow_release.set()
    assert close_duration < 0.1
    assert release_calls == [("alice-id", "lease-token")]
    assert "Resource stream lease release failed" in caplog.text


def test_outer_app_deadline_cancels_blocked_send_and_schedules_lease_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients, _, _ = _authenticated_clients(tmp_path)
    app = clients["alice"].app
    released = threading.Event()

    class _OpenLimiter:
        def is_allowed(self, _user_id: str) -> bool:
            return True

    class _Limiter:
        def acquire(self, _user_id: str) -> str:
            return "lease-token"

        def release(self, _user_id: str, _token: str) -> None:
            released.set()

    async def _one_frame(*_args, **_kwargs):
        yield "event: hello\ndata: {}\n\n"

    monkeypatch.setattr(resource_api, "_resource_event_generator", _one_frame)
    app.state._resource_stream_open_limiter = _OpenLimiter()
    app.state._resource_stream_lease_limiter = _Limiter()
    deadline_middleware = [
        middleware
        for middleware in app.user_middleware
        if middleware.cls is ResourceStreamDeadlineMiddleware
    ]
    assert len(deadline_middleware) == 1
    assert app.user_middleware[0] is deadline_middleware[0]
    deadline_middleware[0].kwargs["deadline_seconds"] = 0.5
    app.middleware_stack = None

    async def _run() -> float:
        body_send_started = asyncio.Event()
        response_status: list[int] = []
        request_sent = False

        async def _send(message: dict) -> None:
            if message["type"] == "http.response.start":
                response_status.append(message["status"])
            elif (
                message["type"] == "http.response.body"
                and message.get("body")
                and message.get("more_body")
            ):
                body_send_started.set()
                await asyncio.Event().wait()

        async def _receive() -> dict:
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        cookie = "; ".join(f"{key}={value}" for key, value in clients["alice"].cookies.items())
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/resource-events/stream",
            "raw_path": b"/api/resource-events/stream",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"testserver"), (b"cookie", cookie.encode())],
            "client": ("testclient", 50_000),
            "server": ("testserver", 80),
        }
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        await app(scope, _receive, _send)
        elapsed = loop.time() - started_at
        assert response_status == [200]
        assert body_send_started.is_set()
        assert await asyncio.to_thread(released.wait, 1)
        for _ in range(100):
            if not resource_api._LEASE_RELEASE_TASKS:
                break
            await asyncio.sleep(0.01)
        assert not resource_api._LEASE_RELEASE_TASKS
        return elapsed

    assert asyncio.run(_run()) < 1.5


def test_per_user_open_rate_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clients, _, _ = _authenticated_clients(tmp_path)
    _install_finite_route_stream(monkeypatch)
    responses = [
        clients["alice"].get("/api/resource-events/stream")
        for _ in range(RESOURCE_EVENT_STREAM_OPEN_LIMIT + 1)
    ]
    assert all(response.status_code == 200 for response in responses[:-1])
    assert responses[-1].status_code == 429


def test_stream_rejects_when_db_pool_has_no_spare_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients, _, _ = _authenticated_clients(tmp_path)
    _install_finite_route_stream(monkeypatch)
    monkeypatch.setattr(
        resource_api,
        "get_settings",
        lambda: SimpleNamespace(database_pool_size=1, database_max_overflow=0),
    )
    response = clients["alice"].get("/api/resource-events/stream")
    assert response.status_code == 503
    assert response.json()["detail"] == RESOURCE_EVENT_STREAM_CAPACITY_UNAVAILABLE


def test_stream_limiter_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clients, _, _ = _authenticated_clients(tmp_path)
    _install_finite_route_stream(monkeypatch)

    class _BrokenLimiter:
        def is_allowed(self, _scope: str) -> bool:
            raise ConnectionError("redis unavailable")

    clients["alice"].app.state._resource_stream_open_limiter = _BrokenLimiter()
    response = clients["alice"].get("/api/resource-events/stream")
    assert response.status_code == 503
    assert response.json()["detail"] == "Resource stream limiter unavailable"
