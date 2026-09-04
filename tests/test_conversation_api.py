"""Tests for the Phase 3 co-writer endpoints + the MCP-enabled Claude call."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from conftest import TEST_SECRET, make_fake_redis
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.claude.provider import (
    AssistantTextEvent,
    FinalEvent,
    StreamEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from songmaker_cli.cowriter.errors import (
    ProviderUnavailableError,
    SafeRouteReasonCode,
    normalize_route_failure,
)
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import (
    Album,
    AvailableModel,
    ChatMessage,
    Conversation,
    Job,
    Song,
    User,
    Version,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

# ── fixtures ──────────────────────────────────────────────────────────


def _fake_user(user_id: str, role: str = "user"):
    user = AuthenticatedUser(
        id=user_id, username=f"u-{user_id}", role=role, is_active=True,
    )
    return lambda: user


def _seed_owned(session, user_id: str) -> None:
    session.add(User(
        id=user_id, username=f"user-{user_id}", password_hash="x", role="user",
    ))
    session.flush()
    session.add(Album(id="alb1", title="Rock", artist="B", created_by=user_id))
    session.add(Song(id="s1", title="Thunder", album_id="alb1", track_number=1))
    session.add(Version(
        id="v1", song_id="s1", version_number=1,
        lyrics="verse", prompt="rock", bpm=120, key_scale="Am", audio_duration=180,
    ))
    session.query(AvailableModel).filter(
        AvailableModel.id.in_(["turbo", "sft"]),
    ).update({"is_active": True}, synchronize_session=False)
    session.commit()


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    factory = init_db(tmp_path / "conv_api.db")
    with factory() as session:
        _seed_owned(session, "u-test")

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
    app.dependency_overrides[get_current_user] = _fake_user("u-test")
    app.include_router(router)
    yield TestClient(app), factory


@pytest.fixture()
def stranger_client(tmp_path: Path) -> TestClient:
    factory = init_db(tmp_path / "conv_api2.db")
    with factory() as session:
        _seed_owned(session, "u-owner")
        session.add(User(
            id="u-spy", username="spy", password_hash="x", role="user",
        ))
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
    app.dependency_overrides[get_current_user] = _fake_user("u-spy")
    app.include_router(router)
    yield TestClient(app), factory


def _mock_claude(text: str = "hello from claude"):
    """Return a patch value that mimics stream_cowriter_turn.

    Yields a single assistant_text event then the terminal FinalEvent.
    """
    async def _gen(*_args, **_kwargs) -> AsyncIterator[StreamEvent]:
        yield AssistantTextEvent(text=text)
        yield FinalEvent(text=text)

    return _gen


def _stream_events(response) -> list[dict]:
    events: list[dict] = []
    for line in response.iter_lines():
        if not line:
            continue
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def _final_event(events: list[dict]) -> dict:
    for event in events:
        if event.get("type") == "final":
            return event
    raise AssertionError(f"no final event in {events!r}")


# ── provider: _build_mcp_cli_cmd ──────────────────────────────────────


def test_mcp_cli_cmd_includes_required_flags():
    from songmaker_cli.claude.provider import (
        MCP_ALLOWED_TOOLS,
        _build_mcp_cli_cmd,
    )

    cmd = _build_mcp_cli_cmd(
        "claude", "claude-opus-4-6", "/tmp/mcp.json",
    )
    assert "--mcp-config" in cmd
    assert cmd[cmd.index("--mcp-config") + 1] == "/tmp/mcp.json"
    assert "--strict-mcp-config" in cmd
    assert "--allowedTools" in cmd
    assert MCP_ALLOWED_TOOLS in cmd
    assert "hi" not in cmd
    assert "sysprompt" not in cmd
    joined = " ".join(cmd)
    assert "postgresql://" not in joined
    assert "DATABASE_URL" not in joined


def test_mcp_config_passes_user_id_to_subprocess_env():
    from songmaker_cli.claude.provider import _build_mcp_config

    cfg = json.loads(_build_mcp_config("user-xyz"))
    srv = cfg["mcpServers"]["songmaker"]
    assert srv["env"]["SONGMAKER_MCP_USER_ID"] == "user-xyz"
    assert "DATABASE_URL" in srv["env"]
    assert srv["args"] == ["-m", "songmaker_cli.mcp_server"]


def test_acall_claude_with_mcp_dispatches_to_cli(monkeypatch):
    import asyncio

    from songmaker_cli.claude import provider

    monkeypatch.setattr(provider, "_require_claude_binary", lambda: "/bin/claude")

    captured = {}

    async def fake_exec(*cmd, **kw):
        captured["cmd"] = cmd
        captured["env"] = kw["env"]
        captured["kwargs"] = kw
        proc = MagicMock()
        proc.pid = 4242
        proc.returncode = 0
        proc.communicate = AsyncMock(
            return_value=(b'{"result":"ok"}', b""),
        )
        return proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr(provider.os, "killpg", MagicMock())

    result = asyncio.run(provider.acall_claude_with_mcp(
        prompt="hi secret-prompt", user_id="u-1", model="claude-opus-4-6",
    ))
    assert result.text == "ok"
    assert "--mcp-config" in captured["cmd"]
    config_arg = captured["cmd"][captured["cmd"].index("--mcp-config") + 1]
    assert not str(config_arg).startswith("{")
    assert "secret-prompt" not in captured["cmd"]
    assert all("DATABASE_URL" not in str(part) for part in captured["cmd"])
    assert captured["kwargs"]["start_new_session"] is True
    assert "DATABASE_URL" not in captured["env"]


def test_acall_claude_with_mcp_returns_unavailable_on_failure(monkeypatch):
    import asyncio

    from songmaker_cli.claude import provider

    monkeypatch.setattr(provider, "_require_claude_binary", lambda: "/bin/claude")

    async def fake_exec(*cmd, **kw):
        proc = MagicMock()
        proc.returncode = 2
        proc.communicate = AsyncMock(return_value=(b"", b"boom"))
        return proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    with pytest.raises(provider.UnavailableError):
        asyncio.run(provider.acall_claude_with_mcp(
            prompt="hi", user_id="u-1",
        ))


def test_acall_claude_with_mcp_raises_when_binary_missing(monkeypatch):
    import asyncio

    from songmaker_cli.claude import provider

    monkeypatch.setattr(provider, "_require_claude_binary", lambda: "/bin/claude")

    async def fake_exec(*cmd, **kw):
        raise FileNotFoundError()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    with pytest.raises(provider.UnavailableError):
        asyncio.run(provider.acall_claude_with_mcp(
            prompt="hi", user_id="u-1",
        ))


def test_acall_claude_with_mcp_timeout_kills_subprocess(monkeypatch):
    import asyncio

    from songmaker_cli.claude import provider

    monkeypatch.setattr(provider, "_require_claude_binary", lambda: "/bin/claude")

    killed = {"value": False}

    async def fake_exec(*cmd, **kw):
        proc = MagicMock()
        proc.pid = 4242
        proc.returncode = None
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        proc.wait = AsyncMock(return_value=None)
        return proc

    def _killpg(pid, _sig):
        killed["value"] = True

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr(provider.os, "killpg", _killpg)

    with pytest.raises(provider.UnavailableError):
        asyncio.run(provider.acall_claude_with_mcp(
            prompt="hi", user_id="u-1", timeout_seconds=1,
        ))
    assert killed["value"] is True


# ── /api/chat/turn ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("provider", "route", "tools_available"),
    [
        ("grok", "cli", True),
        ("grok", "api", True),
        ("claude", "api", True),
    ],
)
def test_chat_turn_uses_the_selected_provider_route_capability(
    client, provider, route, tools_available,
):
    from songmaker_cli.conversation_api import (
        COWRITER_TEXT_ONLY_INSTRUCTIONS,
        COWRITER_TOOLS_AVAILABLE_INSTRUCTIONS,
    )
    from songmaker_cli.db.queries.settings import set_cowriter_settings

    c, factory = client
    with factory() as session:
        set_cowriter_settings(
            session,
            provider,
            "claude-opus-4-6" if provider == "claude" else "grok-4.6",
            routes={
                "claude": "api" if provider == "claude" else "cli",
                "grok": route,
                "codex": "cli",
            },
        )
        session.commit()

    captured: dict[str, object] = {}

    async def _capture(**kwargs) -> AsyncIterator[StreamEvent]:
        captured.update(kwargs)
        yield FinalEvent(text="ok")

    with patch("songmaker_cli.conversation_api.stream_cowriter_turn", _capture):
        response = c.post("/api/chat/turn", json={"message": "hey"})

    assert response.status_code == 200
    prompt = captured["system"]
    assert isinstance(prompt, str)
    assert (COWRITER_TOOLS_AVAILABLE_INSTRUCTIONS in prompt) is tools_available
    assert (COWRITER_TEXT_ONLY_INSTRUCTIONS in prompt) is (not tools_available)
    if provider == "grok" and route == "cli":
        assert "<songmaker_tool_call>" in prompt
        assert "update_song_lyrics" in prompt


def test_chat_turn_streams_sse_and_stores_messages(client):
    c, factory = client
    mock_stream = _mock_claude("ok")
    with patch(
        "songmaker_cli.conversation_api.stream_cowriter_turn",
        mock_stream,
    ):
        resp = c.post("/api/chat/turn", json={"message": "hey"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _stream_events(resp)
    # At least one streaming (assistant_text) event + a final frame.
    assert any(e["type"] == "assistant_text" for e in events)
    final = _final_event(events)
    assert final["user_message"]["content"] == "hey"
    assert final["assistant_message"]["content"] == "ok"
    conv_id = final["conversation_id"]

    with factory() as session:
        convs = session.query(Conversation).all()
        assert len(convs) == 1
        assert convs[0].id == conv_id
        assert convs[0].user_id == "u-test"
        assert convs[0].archived_at is None
        msgs = session.query(ChatMessage).order_by(ChatMessage.created_at).all()
        assert [m.role for m in msgs] == ["user", "assistant"]
        assert all(m.conversation_id == conv_id for m in msgs)
        job = session.query(Job).filter_by(type="chat").one()
        assert job.status == "completed"


def test_chat_turn_completes_when_its_heartbeat_task_fails(client):
    c, factory = client

    async def _failed_heartbeat(*_args, **_kwargs) -> None:
        raise RuntimeError("database unavailable")

    with patch(
        "songmaker_cli.conversation_api.stream_cowriter_turn",
        _mock_claude("ok"),
    ), patch(
        "songmaker_cli.jobs._runtime._keep_chat_job_heartbeat",
        _failed_heartbeat,
    ):
        response = c.post("/api/chat/turn", json={"message": "hey"})

    assert response.status_code == 200
    assert _final_event(_stream_events(response))["assistant_message"]["content"] == "ok"
    with factory() as session:
        job = session.query(Job).filter_by(type="chat").one()
        assert job.status == "completed"


def test_chat_turn_disconnect_reaps_provider_before_asgi_23_response_returns(client):
    import asyncio

    from songmaker_cli.api_models import ChatTurnV2Request
    from songmaker_cli.conversation_api import api_chat_turn

    c, factory = client

    async def _exercise() -> None:
        heartbeat_started = asyncio.Event()
        heartbeat_stopped = asyncio.Event()
        body_sent = asyncio.Event()
        reaper_finished = asyncio.Event()

        async def _keep_heartbeat(*_args, **_kwargs) -> None:
            heartbeat_started.set()
            try:
                await asyncio.Future()
            finally:
                heartbeat_stopped.set()

        async def _consume(*_args, **_kwargs) -> AsyncIterator[StreamEvent]:
            await heartbeat_started.wait()
            yield AssistantTextEvent(text="partial")
            await asyncio.Future()

        async def _spawn(*_args, **_kwargs) -> MagicMock:
            process = MagicMock()
            process.stdin = None
            return process

        async def _reap(_process) -> bool:
            await asyncio.sleep(0)
            reaper_finished.set()
            return False

        request = Request({"type": "http", "app": c.app})
        user = AuthenticatedUser(
            id="u-test",
            username="u-u-test",
            role="user",
            is_active=True,
        )
        with factory() as session:
            with patch(
                "songmaker_cli.jobs._runtime._keep_chat_job_heartbeat",
                _keep_heartbeat,
            ), patch(
                "songmaker_cli.claude.provider._spawn_reserved_async_cli_process",
                _spawn,
            ), patch(
                "songmaker_cli.claude.provider._consume_stream",
                _consume,
            ), patch(
                "songmaker_cli.claude.provider._reap_process_group",
                _reap,
            ):
                response = await api_chat_turn(
                    ChatTurnV2Request(message="hey"),
                    request,
                    user,
                    session,
                )

                async def _receive() -> None:
                    await body_sent.wait()
                    return {"type": "http.disconnect"}

                async def _send(message) -> None:
                    if message["type"] == "http.response.body":
                        body_sent.set()

                await response(
                    {"type": "http", "asgi": {"spec_version": "2.3"}},
                    _receive,
                    _send,
                )

                assert heartbeat_stopped.is_set()
                assert reaper_finished.is_set()

    asyncio.run(_exercise())

    with factory() as session:
        job = session.query(Job).filter_by(type="chat").one()
        assert job.status == "failed"
        assert job.error_type == "cancelled"
        assert job.error == "Turn cancelled by the client."


def test_chat_turn_start_response_failure_cancels_unstarted_stream(client):
    import asyncio

    from starlette.requests import ClientDisconnect

    from songmaker_cli.api_models import ChatTurnV2Request
    from songmaker_cli.conversation_api import api_chat_turn

    c, factory = client

    async def _exercise() -> None:
        heartbeat_started = asyncio.Event()
        heartbeat_stopped = asyncio.Event()
        provider_started = False

        async def _keep_heartbeat(*_args, **_kwargs) -> None:
            heartbeat_started.set()
            try:
                await asyncio.Future()
            finally:
                heartbeat_stopped.set()

        async def _stream(*_args, **_kwargs) -> AsyncIterator[StreamEvent]:
            nonlocal provider_started
            provider_started = True
            yield AssistantTextEvent(text="partial")

        request = Request({"type": "http", "app": c.app})
        user = AuthenticatedUser(
            id="u-test",
            username="u-u-test",
            role="user",
            is_active=True,
        )
        with factory() as session:
            with patch(
                "songmaker_cli.jobs._runtime._keep_chat_job_heartbeat",
                _keep_heartbeat,
            ), patch(
                "songmaker_cli.conversation_api.stream_cowriter_turn",
                _stream,
            ):
                response = await api_chat_turn(
                    ChatTurnV2Request(message="hey"),
                    request,
                    user,
                    session,
                )
                await heartbeat_started.wait()

                async def _receive() -> None:
                    await asyncio.Future()

                async def _send(message) -> None:
                    if message["type"] == "http.response.start":
                        raise OSError("client disconnected before stream start")

                with pytest.raises(ClientDisconnect):
                    await response(
                        {"type": "http", "asgi": {"spec_version": "2.4"}},
                        _receive,
                        _send,
                    )

        assert heartbeat_stopped.is_set()
        assert not provider_started

    asyncio.run(_exercise())

    with factory() as session:
        job = session.query(Job).filter_by(type="chat").one()
        assert job.status == "failed"
        assert job.error_type == "cancelled"
        assert job.error == "Turn cancelled by the client."


def test_chat_turn_marks_job_cancelled_when_stream_generator_closes(client):
    import asyncio

    from songmaker_cli.api_models import ChatTurnV2Request
    from songmaker_cli.conversation_api import api_chat_turn

    c, factory = client

    async def _exercise() -> None:
        heartbeat_started = asyncio.Event()
        heartbeat_stopped = asyncio.Event()
        provider_reaped = asyncio.Event()
        provider_close_count = 0

        async def _keep_heartbeat(*_args, **_kwargs) -> None:
            heartbeat_started.set()
            try:
                await asyncio.Future()
            finally:
                heartbeat_stopped.set()

        async def _acall(*_args, **_kwargs) -> AsyncIterator[StreamEvent]:
            nonlocal provider_close_count
            await heartbeat_started.wait()
            try:
                yield AssistantTextEvent(text="partial")
                await asyncio.Future()
            finally:
                provider_close_count += 1
                provider_reaped.set()

        request = Request({"type": "http", "app": c.app})
        user = AuthenticatedUser(
            id="u-test",
            username="u-u-test",
            role="user",
            is_active=True,
        )
        with factory() as session:
            with patch(
                "songmaker_cli.jobs._runtime._keep_chat_job_heartbeat",
                _keep_heartbeat,
            ), patch(
                "songmaker_cli.cowriter.claude_adapter.acall_claude_with_mcp_stream",
                _acall,
            ):
                response = await api_chat_turn(
                    ChatTurnV2Request(message="hey"),
                    request,
                    user,
                    session,
                )
                stream = response.body_iterator
                await anext(stream)
                await stream.aclose()
                assert heartbeat_stopped.is_set()
                assert provider_reaped.is_set()
                assert provider_close_count == 1

    asyncio.run(_exercise())

    with factory() as session:
        job = session.query(Job).filter_by(type="chat").one()
        assert job.status == "failed"
        assert job.error_type == "cancelled"
        assert job.error == "Turn cancelled by the client."


def test_chat_turn_closing_after_completion_keeps_job_completed(client):
    import asyncio

    from songmaker_cli.api_models import ChatTurnV2Request
    from songmaker_cli.conversation_api import api_chat_turn

    c, factory = client

    async def _exercise() -> None:
        request = Request({"type": "http", "app": c.app})
        user = AuthenticatedUser(
            id="u-test",
            username="u-u-test",
            role="user",
            is_active=True,
        )
        with factory() as session:
            with patch(
                "songmaker_cli.conversation_api.stream_cowriter_turn",
                _mock_claude("ok"),
            ):
                response = await api_chat_turn(
                    ChatTurnV2Request(message="hey"),
                    request,
                    user,
                    session,
                )
                stream = response.body_iterator
                await anext(stream)
                await anext(stream)
                await stream.aclose()

    asyncio.run(_exercise())

    with factory() as session:
        job = session.query(Job).filter_by(type="chat").one()
        assert job.status == "completed"
        assert job.error is None
        assert job.error_type is None


def test_chat_turn_reuses_active_conversation_across_turns(client):
    c, factory = client
    mock_stream = _mock_claude()
    with patch(
        "songmaker_cli.conversation_api.stream_cowriter_turn",
        mock_stream,
    ):
        r1 = c.post("/api/chat/turn", json={"message": "one"})
        r2 = c.post("/api/chat/turn", json={"message": "two"})

    f1 = _final_event(_stream_events(r1))
    f2 = _final_event(_stream_events(r2))
    assert f1["conversation_id"] == f2["conversation_id"]
    with factory() as session:
        assert session.query(Conversation).count() == 1
        assert session.query(ChatMessage).count() == 4


def test_chat_turn_injects_current_song_block(client):
    c, _ = client
    captured_kwargs: dict = {}

    async def _capture(*args, **kwargs):
        captured_kwargs.update(kwargs)
        yield AssistantTextEvent(text="ok")
        yield FinalEvent(text="ok")

    with patch(
        "songmaker_cli.conversation_api.stream_cowriter_turn",
        _capture,
    ):
        resp = c.post(
            "/api/chat/turn",
            json={"message": "rewrite the chorus", "current_song_id": "s1"},
        )
    assert resp.status_code == 200
    _ = _stream_events(resp)
    messages = captured_kwargs["messages"]
    last_user = messages[-1]["content"]
    assert "<current_song>" in last_user
    assert "title: Thunder" in last_user
    assert "lyrics:\nverse" in last_user
    assert captured_kwargs["user_id"] == "u-test"


def test_chat_turn_forwards_tool_call_events(client):
    c, _ = client

    async def _gen(*_args, **_kwargs):
        yield ToolCallEvent(
            tool_use_id="tu-1",
            name="mcp__songmaker__get_song",
            input={"song_id": "s1"},
        )
        yield ToolResultEvent(
            tool_use_id="tu-1", content="song", is_error=False,
        )
        yield AssistantTextEvent(text="here")
        yield FinalEvent(text="here")

    with patch(
        "songmaker_cli.conversation_api.stream_cowriter_turn", _gen,
    ):
        resp = c.post("/api/chat/turn", json={"message": "call a tool"})

    events = _stream_events(resp)
    types = [e["type"] for e in events]
    assert "tool_call" in types
    tool_event = next(e for e in events if e["type"] == "tool_call")
    assert tool_event["name"] == "mcp__songmaker__get_song"
    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_result["tool_use_id"] == "tu-1"


def test_chat_turn_rejects_other_users_song(stranger_client):
    c, _ = stranger_client
    called = {"value": False}

    async def _gen(*_args, **_kwargs):
        called["value"] = True
        yield FinalEvent(text="")

    with patch(
        "songmaker_cli.conversation_api.stream_cowriter_turn", _gen,
    ):
        resp = c.post(
            "/api/chat/turn",
            json={"message": "spy", "current_song_id": "s1"},
        )
    assert resp.status_code == 404
    assert called["value"] is False


def test_chat_turn_unexpected_error_emits_error_frame_and_marks_job_failed(
    client,
):
    c, factory = client

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("kaboom")
        yield  # pragma: no cover

    with patch(
        "songmaker_cli.conversation_api.stream_cowriter_turn",
        _boom,
    ):
        resp = c.post("/api/chat/turn", json={"message": "oops"})

    assert resp.status_code == 200
    events = _stream_events(resp)
    assert any(
        e.get("type") == "error" and e.get("status") == 500 for e in events
    )

    with factory() as session:
        from songmaker_cli.db.models import Job

        jobs = session.query(Job).all()
        assert len(jobs) == 1
        assert jobs[0].status == "failed"


def test_chat_turn_unavailable_emits_503_error_frame(client):
    c, factory = client
    secret_sentinel = "do-not-expose-route-secret"

    async def _down(*_args, **_kwargs):
        try:
            raise RuntimeError(secret_sentinel)
        except RuntimeError as cause:
            raise ProviderUnavailableError(
                "claude",
                "cli",
                normalize_route_failure(SafeRouteReasonCode.CLI_AUTH_REJECTED),
            ) from cause
        yield

    with patch(
        "songmaker_cli.conversation_api.stream_cowriter_turn",
        _down,
    ):
        resp = c.post("/api/chat/turn", json={"message": "hi"})
    assert resp.status_code == 200
    events = _stream_events(resp)
    err = next(e for e in events if e.get("type") == "error")
    assert err["status"] == 503
    assert err == {
        "type": "error",
        "status": 503,
        "provider": "claude",
        "route": "cli",
        "reason": {
            "code": "cli_auth_rejected",
            "message": "CLI login was rejected or has expired.",
        },
    }
    assert secret_sentinel not in resp.text

    with factory() as session:
        assert session.query(Conversation).count() == 0
        assert session.query(ChatMessage).count() == 0


# ── /api/conversations ────────────────────────────────────────────────


def test_list_conversations_scoped_to_user(client):
    c, factory = client
    with factory() as session:
        session.add(Conversation(id="mine-1", user_id="u-test", title="mine"))
        session.add(User(
            id="u-other", username="other", password_hash="x", role="user",
        ))
        session.flush()
        session.add(Conversation(id="not-mine", user_id="u-other", title="no"))
        session.commit()

    resp = c.get("/api/conversations")
    assert resp.status_code == 200
    ids = [conv["id"] for conv in resp.json()["conversations"]]
    assert ids == ["mine-1"]


def test_list_conversations_includes_counts(client):
    c, factory = client
    mock_stream = _mock_claude()
    with patch(
        "songmaker_cli.conversation_api.stream_cowriter_turn",
        mock_stream,
    ):
        c.post("/api/chat/turn", json={"message": "a"})

    resp = c.get("/api/conversations")
    conv = resp.json()["conversations"][0]
    assert conv["message_count"] == 2
    assert conv["last_message_at"] is not None


def test_get_conversation_returns_messages(client):
    c, _ = client
    mock_stream = _mock_claude("reply!")
    with patch(
        "songmaker_cli.conversation_api.stream_cowriter_turn",
        mock_stream,
    ):
        turn = c.post("/api/chat/turn", json={"message": "question?"})
    conv_id = _final_event(_stream_events(turn))["conversation_id"]

    resp = c.get(f"/api/conversations/{conv_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == conv_id
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["content"] == "question?"
    assert body["messages"][1]["content"] == "reply!"


def test_get_conversation_rejects_other_user(client):
    c, factory = client
    with factory() as session:
        session.add(User(
            id="u-owner2", username="o", password_hash="x", role="user",
        ))
        session.flush()
        session.add(Conversation(id="not-mine", user_id="u-owner2", title="x"))
        session.commit()
    resp = c.get("/api/conversations/not-mine")
    assert resp.status_code == 404


def test_get_conversation_404_when_unknown(client):
    c, _ = client
    assert c.get("/api/conversations/bogus").status_code == 404


def test_new_conversation_archives_active(client):
    c, factory = client
    mock_stream = _mock_claude()
    with patch(
        "songmaker_cli.conversation_api.stream_cowriter_turn",
        mock_stream,
    ):
        turn = c.post("/api/chat/turn", json={"message": "hi"})
    old_id = _final_event(_stream_events(turn))["conversation_id"]

    resp = c.post("/api/conversations/new")
    assert resp.status_code == 200
    new_id = resp.json()["id"]
    assert new_id != old_id

    with factory() as session:
        old = session.query(Conversation).filter_by(id=old_id).one()
        new = session.query(Conversation).filter_by(id=new_id).one()
        assert old.archived_at is not None
        assert new.archived_at is None


def test_new_conversation_without_active(client):
    c, _ = client
    resp = c.post("/api/conversations/new")
    assert resp.status_code == 200
    body = resp.json()
    assert body["archived_at"] is None
    assert body["message_count"] == 0


def test_delete_conversation_removes_messages(client):
    c, factory = client
    mock_stream = _mock_claude()
    with patch(
        "songmaker_cli.conversation_api.stream_cowriter_turn",
        mock_stream,
    ):
        turn = c.post("/api/chat/turn", json={"message": "bye"})
    conv_id = _final_event(_stream_events(turn))["conversation_id"]

    resp = c.delete(f"/api/conversations/{conv_id}")
    assert resp.status_code == 200

    with factory() as session:
        assert session.query(Conversation).filter_by(id=conv_id).count() == 0
        assert session.query(ChatMessage).count() == 0


def test_delete_conversation_rejects_other_user(client):
    c, factory = client
    with factory() as session:
        session.add(User(
            id="u-owner3", username="o", password_hash="x", role="user",
        ))
        session.flush()
        session.add(Conversation(
            id="not-mine-2", user_id="u-owner3", title="x",
        ))
        session.commit()
    resp = c.delete("/api/conversations/not-mine-2")
    assert resp.status_code == 404
    with factory() as session:
        assert session.query(Conversation).filter_by(id="not-mine-2").count() == 1
