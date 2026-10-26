"""Tests for the Phase 3 co-writer endpoints + the MCP-enabled Claude call."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from conftest import (
    make_authenticated_user,
    make_router_app,
    make_router_ctx,
    seed_user,
    web_client,
)
from fake_agent_service import (
    CowriterStack,
    answers,
    attach_cowriter_service,
    fails_to_connect,
    held_until,
    signed_in_request,
    streams,
)
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.constants import CURRENT_SONG_FRESHNESS_NOTE
from songmaker_cli.cowriter import service_runs
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import (
    Album,
    AvailableModel,
    ChatMessage,
    Conversation,
    Generation,
    Job,
    Song,
    User,
    Version,
)

# ── fixtures ──────────────────────────────────────────────────────────


def _seed_owned(session, user_id: str) -> None:
    session.add(User(
        id=user_id, username=f"user-{user_id}", role="user",
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


@pytest.fixture
def client(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session]]:
    factory = init_db(tmp_path / "conv_api.db")
    with factory() as session:
        _seed_owned(session, "u-test")

    app = make_router_app(
        make_router_ctx(tmp_path, db=factory),
        user=make_authenticated_user("u-test", username="u-u-test"),
    )
    return web_client(app), factory


@pytest.fixture
def stranger_client(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session]]:
    factory = init_db(tmp_path / "conv_api2.db")
    with factory() as session:
        _seed_owned(session, "u-owner")
        session.add(User(
            id="u-spy", username="spy", role="user",
        ))
        session.commit()

    app = make_router_app(
        make_router_ctx(tmp_path, db=factory),
        user=make_authenticated_user("u-spy", username="u-u-spy"),
    )
    return web_client(app), factory


@pytest.fixture
def service(client, monkeypatch) -> CowriterStack:
    """The agent service and the realm behind the signed-in musician's turns."""
    c, factory = client
    return attach_cowriter_service(c, factory, monkeypatch, "u-test")


def _stream_events(response) -> list[dict]:
    """Parse the SSE body into its frames."""
    events: list[dict] = []
    for line in response.iter_lines():
        if not line:
            continue
        if line.startswith("data: "):
            event = json.loads(line[len("data: "):])
            events.append(event)
    return events


def _final_event(events: list[dict]) -> dict:
    for event in events:
        if event.get("type") == "final":
            return event
    raise AssertionError(f"no final event in {events!r}")


# ── provider: _build_mcp_cli_cmd ──────────────────────────────────────


def test_mcp_cli_cmd_includes_required_flags():
    from agent_providers.claude.provider import _build_mcp_cli_cmd
    from agent_providers.config import current_config

    cmd = _build_mcp_cli_cmd(
        "claude", "claude-opus-4-6", "/tmp/mcp.json", current_config().mcp_server,
    )
    assert "--mcp-config" in cmd
    assert cmd[cmd.index("--mcp-config") + 1] == "/tmp/mcp.json"
    assert "--strict-mcp-config" in cmd
    assert "--allowedTools" in cmd
    assert "mcp__songmaker__*" in cmd
    assert "hi" not in cmd
    assert "sysprompt" not in cmd
    joined = " ".join(cmd)
    assert "postgresql://" not in joined
    assert "DATABASE_URL" not in joined


def test_mcp_config_passes_user_id_to_subprocess_env():
    from agent_providers.claude.provider import _build_mcp_config
    from agent_providers.config import current_config

    cfg = json.loads(_build_mcp_config(current_config().mcp_server, "user-xyz"))
    srv = cfg["mcpServers"]["songmaker"]
    assert srv["env"]["SONGMAKER_MCP_USER_ID"] == "user-xyz"
    assert "DATABASE_URL" in srv["env"]
    assert srv["args"] == ["-m", "songmaker_cli.mcp_server"]


def test_acall_claude_with_mcp_dispatches_to_cli(monkeypatch):
    import asyncio

    from agent_providers.claude import provider

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

    from agent_providers.claude import provider

    monkeypatch.setattr(provider, "_require_claude_binary", lambda: "/bin/claude")

    async def fake_exec(*cmd, **kw):
        proc = MagicMock()
        proc.returncode = 2
        proc.communicate = AsyncMock(return_value=(b"", b"boom"))
        return proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    call = provider.acall_claude_with_mcp(prompt="hi", user_id="u-1")
    with pytest.raises(provider.UnavailableError):
        asyncio.run(call)


def test_acall_claude_with_mcp_raises_when_binary_missing(monkeypatch):
    import asyncio

    from agent_providers.claude import provider

    monkeypatch.setattr(provider, "_require_claude_binary", lambda: "/bin/claude")

    async def fake_exec(*cmd, **kw):
        raise FileNotFoundError()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    call = provider.acall_claude_with_mcp(prompt="hi", user_id="u-1")
    with pytest.raises(provider.UnavailableError):
        asyncio.run(call)


def test_acall_claude_with_mcp_timeout_kills_subprocess(monkeypatch):
    import asyncio

    from agent_providers.claude import provider

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

    call = provider.acall_claude_with_mcp(
        prompt="hi", user_id="u-1", timeout_seconds=1,
    )
    with pytest.raises(provider.UnavailableError):
        asyncio.run(call)
    assert killed["value"] is True


# ── /api/chat/turn ────────────────────────────────────────────────────


def test_chat_turn_streams_sse_and_stores_messages(client, service):
    c, factory = client
    service.agent.reply_with(answers("ok"))

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


_RETURNING_USER = make_authenticated_user("u-test", username="u-u-test")


def _while_a_turn_runs(client, service, look):
    """Hold one turn open on "Ja bitte", return what ``look`` sees meanwhile, then let it finish."""
    import asyncio

    from songmaker_cli.api_models import ChatTurnV2Request
    from songmaker_cli.conversation_api import api_chat_turn

    c, factory = client

    async def _exercise():
        reply_released = asyncio.Event()
        service.agent.reply_with(held_until(reply_released, "done"))
        request = signed_in_request(c)
        with factory() as session:
            response = await api_chat_turn(
                ChatTurnV2Request(message="Ja bitte"), request, _RETURNING_USER, session,
            )
            stream = response.body_iterator
            await anext(stream)
            seen_mid_turn = await look()
            reply_released.set()
            async for _frame in stream:
                pass
            return seen_mid_turn

    return asyncio.run(_exercise())


def _conversation_seen_by_a_returning_panel(factory) -> tuple[list[tuple[str, str]], bool]:
    from songmaker_cli.conversation_api import api_conversation_messages, api_list_conversations

    with factory() as reader:
        active = api_list_conversations(_RETURNING_USER, reader).conversations[0]
        conversation = api_conversation_messages(active.id, _RETURNING_USER, reader)
        messages = [(message.role, message.content) for message in conversation.messages]
        return messages, conversation.turn_running


def test_a_running_turn_already_shows_its_user_message_in_the_conversation(client, service):
    """A panel opened while the reply is still streaming finds the message sent (#1014)."""
    _c, factory = client

    async def _look():
        return _conversation_seen_by_a_returning_panel(factory)

    assert _while_a_turn_runs(client, service, _look) == ([("user", "Ja bitte")], True)
    assert _conversation_seen_by_a_returning_panel(factory) == (
        [("user", "Ja bitte"), ("assistant", "done")],
        False,
    )


def test_a_turn_sent_while_another_runs_is_refused_and_the_message_answered_once(client, service):
    """Try again or a second tab cannot start a second turn on the same message (#1014)."""
    from fastapi import HTTPException

    from songmaker_cli.api_models import ChatTurnV2Request
    from songmaker_cli.conversation_api import api_chat_turn

    c, factory = client

    async def _send_it_again():
        turn = ChatTurnV2Request(message="Ja bitte")
        with factory() as session, pytest.raises(HTTPException) as refused:
            await api_chat_turn(turn, signed_in_request(c), _RETURNING_USER, session)
        return refused.value.status_code

    assert _while_a_turn_runs(client, service, _send_it_again) == 409
    assert _conversation_seen_by_a_returning_panel(factory) == (
        [("user", "Ja bitte"), ("assistant", "done")],
        False,
    )
    assert len(service.agent.runs) == 1
    with factory() as session:
        assert [job.status for job in session.query(Job).filter_by(type="chat")] == ["completed"]


@pytest.mark.parametrize(
    ("chat_job_status", "archived", "turn_running"),
    [
        ("running", False, True),
        ("failed", False, False),
        ("running", True, False),
    ],
    ids=["job-running", "job-reaped-after-process-death", "archived-conversation"],
)
def test_the_chat_job_decides_whether_a_turn_is_running(
    client, chat_job_status, archived, turn_running,
):
    """A message left behind by a dead turn is not a running turn once the reaper ends its job."""
    from datetime import UTC, datetime

    c, factory = client
    with factory() as session:
        session.add(Conversation(
            id="conv-1",
            user_id="u-test",
            archived_at=datetime.now(UTC) if archived else None,
        ))
        session.add(ChatMessage(conversation_id="conv-1", role="user", content="Ja bitte"))
        session.add(Job(type="chat", user_id="u-test", status=chat_job_status))
        session.commit()

    body = c.get("/api/conversations/conv-1").json()

    assert [m["content"] for m in body["messages"]] == ["Ja bitte"]
    assert body["turn_running"] is turn_running


@pytest.mark.parametrize("chat_job_status", ["queued", "running"])
def test_a_turn_the_web_process_ran_before_a_restart_no_longer_runs_after_it(
    tmp_path, mock_arq_pool, chat_job_status,
):
    """A restart mid-turn leaves the message unanswered at once, not locked for minutes (#1014)."""
    from conftest import login_and_csrf, make_test_app

    def _seed_a_turn_the_restart_interrupted(session) -> None:
        musician = seed_user(session, "musician", role="user")
        session.add(Conversation(id="conv-1", user_id=musician.id))
        session.add(ChatMessage(conversation_id="conv-1", role="user", content="Ja bitte"))
        session.add(Job(type="chat", user_id=musician.id, status=chat_job_status))

    c, factory = make_test_app(tmp_path, seed_db=_seed_a_turn_the_restart_interrupted)
    with c:
        login_and_csrf(c, "musician")
        body = c.get("/api/conversations/conv-1").json()

    assert [m["content"] for m in body["messages"]] == ["Ja bitte"]
    assert body["turn_running"] is False
    with factory() as session:
        assert [job.error_type for job in session.query(Job).filter_by(type="chat")] == [
            "server_restart",
        ]


def test_chat_turn_completes_when_its_heartbeat_task_fails(client, service):
    c, factory = client
    service.agent.reply_with(answers("ok"))

    async def _failed_heartbeat(*_args, **_kwargs) -> None:
        raise RuntimeError("database unavailable")

    with patch("songmaker_cli.jobs._runtime._keep_chat_job_heartbeat", _failed_heartbeat):
        response = c.post("/api/chat/turn", json={"message": "hey"})

    assert response.status_code == 200
    assert _final_event(_stream_events(response))["assistant_message"]["content"] == "ok"
    with factory() as session:
        job = session.query(Job).filter_by(type="chat").one()
        assert job.status == "completed"


def test_a_turn_that_cannot_open_its_stream_no_longer_counts_as_running(client, service):
    """A turn failing before its first event still ends its job, so no panel waits on it forever."""
    c, factory = client
    service.agent.reply_with(fails_to_connect(RuntimeError("the client could not be built")))

    c.post("/api/chat/turn", json={"message": "hey"})

    with factory() as session:
        conversation_id = session.query(Conversation).one().id
    assert c.get(f"/api/conversations/{conversation_id}").json()["turn_running"] is False


async def _leave_mid_reply(response) -> None:
    import asyncio

    first_frame_sent = asyncio.Event()

    async def _receive() -> dict:
        await first_frame_sent.wait()
        return {"type": "http.disconnect"}

    async def _send(message) -> None:
        if message["type"] == "http.response.body":
            first_frame_sent.set()

    await response({"type": "http", "asgi": {"spec_version": "2.3"}}, _receive, _send)


async def _leave_before_the_reply_starts(response) -> None:
    import asyncio

    from starlette.requests import ClientDisconnect

    async def _receive() -> dict:
        await asyncio.Future()

    async def _send(message) -> None:
        if message["type"] == "http.response.start":
            raise OSError("client disconnected before stream start")

    with pytest.raises(ClientDisconnect):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, _receive, _send)


async def _stop_reading_the_reply(response) -> None:
    stream = response.body_iterator
    await anext(stream)
    await stream.aclose()


@pytest.mark.parametrize(
    "leave",
    [_leave_mid_reply, _leave_before_the_reply_starts, _stop_reading_the_reply],
    ids=["disconnect-mid-reply", "disconnect-before-start", "stream-closed"],
)
def test_a_turn_whose_client_leaves_runs_to_completion_and_keeps_its_reply(
    client, service, leave,
):
    """Head ruling on #1014: a started turn finishes; a client that leaves only stops listening."""
    import asyncio

    from songmaker_cli.api_models import ChatTurnV2Request
    from songmaker_cli.conversation_api import api_chat_turn

    c, factory = client
    run_id = str(uuid.uuid4())

    async def _exercise() -> None:
        reply_released = asyncio.Event()
        service.agent.reply_with(held_until(reply_released, "Erledigt.", run_id=run_id))
        user = make_authenticated_user("u-test", username="u-u-test")
        with factory() as session:
            response = await api_chat_turn(
                ChatTurnV2Request(message="Ja bitte"), signed_in_request(c), user, session,
            )
            await leave(response)
            reply_released.set()
            await asyncio.gather(
                *(asyncio.all_tasks() - {asyncio.current_task()}), return_exceptions=True,
            )

    asyncio.run(_exercise())

    assert service_runs.holder(run_id) is None
    with factory() as session:
        job = session.query(Job).filter_by(type="chat").one()
        assert job.status == "completed"
        messages = session.query(ChatMessage).order_by(ChatMessage.created_at).all()
        assert [(m.role, m.content) for m in messages] == [
            ("user", "Ja bitte"),
            ("assistant", "Erledigt."),
        ]


def test_chat_turn_closing_after_completion_keeps_job_completed(client, service):
    import asyncio

    from songmaker_cli.api_models import ChatTurnV2Request
    from songmaker_cli.conversation_api import api_chat_turn

    c, factory = client
    service.agent.reply_with(answers("ok"))

    async def _exercise() -> None:
        user = make_authenticated_user("u-test", username="u-u-test")
        with factory() as session:
            response = await api_chat_turn(
                ChatTurnV2Request(message="hey"), signed_in_request(c), user, session,
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


def test_chat_turn_reuses_active_conversation_across_turns(client, service):
    c, factory = client
    service.agent.reply_with(answers("ok"))

    r1 = c.post("/api/chat/turn", json={"message": "one"})
    r2 = c.post("/api/chat/turn", json={"message": "two"})

    f1 = _final_event(_stream_events(r1))
    f2 = _final_event(_stream_events(r2))
    assert f1["conversation_id"] == f2["conversation_id"]
    with factory() as session:
        assert session.query(Conversation).count() == 1
        assert session.query(ChatMessage).count() == 4


def test_chat_turn_carries_history_memory_mentions_and_take_into_the_next_turn(client, service):
    """Spec: REQ-COWRITER-09 -- every turn of the active conversation reaches the run with its
    history, memory, mentions, and take context."""
    c, factory = client
    with factory() as session:
        session.add(Generation(
            id="gen1",
            song_id="s1",
            version_id="v1",
            generation_number=1,
            mp3_path="take.mp3",
            whisper_text="a sung take",
        ))
        session.commit()

    assert c.put("/api/memory/user", json={"body": "prefers vivid imagery"}).status_code == 200
    assert c.put("/api/memory/songs/s1", json={"body": "chorus is locked"}).status_code == 200
    assert c.put("/api/memory/albums/alb1", json={"body": "album is nocturnal"}).status_code == 200

    first_request = {
        "message": "remember the verse",
        "current_song_id": "s1",
        "mentioned_version_ids": ["v1"],
        "current_generation_id": "gen1",
    }
    service.agent.reply_with(answers("first answer"))
    first = c.post("/api/chat/turn", json=first_request)
    first_final = _final_event(_stream_events(first))
    service.agent.reply_with(answers("second answer"))
    second = c.post("/api/chat/turn", json={**first_request, "message": "continue the verse"})

    second_final = _final_event(_stream_events(second))
    assert second_final["conversation_id"] == first_final["conversation_id"]
    second_messages = service.agent.last_run.messages
    second_context = "\n".join(m["text"] for m in second_messages if m["role"] == "user")
    assert "prefers vivid imagery" in second_context
    assert "chorus is locked" in second_context
    assert "album is nocturnal" in second_context
    assert "v1" in second_context
    assert "gen1" in second_context
    assert [message["text"] for message in second_messages[:2]] == [
        "remember the verse",
        "first answer",
    ]
    assert "continue the verse" in second_messages[2]["text"]

    with factory() as session:
        messages = session.query(ChatMessage).order_by(ChatMessage.created_at).all()
        assert [message.content for message in messages] == [
            "remember the verse",
            "first answer",
            "continue the verse",
            "second answer",
        ]


def test_chat_turn_injects_current_song_block(client, service):
    c, _ = client

    resp = c.post(
        "/api/chat/turn",
        json={"message": "rewrite the chorus", "current_song_id": "s1"},
    )

    assert resp.status_code == 200
    last_user = service.agent.last_run.messages[-1]["text"]
    assert f"{CURRENT_SONG_FRESHNESS_NOTE}\n<current_song>" in last_user
    assert "title: Thunder" in last_user
    assert "lyrics:\nverse" in last_user


def test_chat_turn_forwards_tool_call_events(client, service):
    c, _ = client

    async def _frames(_run, script):
        yield script.started()
        yield script.tool_call("tu-1", "get_song", {"song_id": "s1"})
        yield script.tool_result("tu-1", "song")
        yield script.text("here")
        yield script.succeeded("here")

    service.agent.reply_with(streams(_frames))

    resp = c.post("/api/chat/turn", json={"message": "call a tool"})

    events = _stream_events(resp)
    types = [e["type"] for e in events]
    assert "tool_call" in types
    tool_event = next(e for e in events if e["type"] == "tool_call")
    assert tool_event["name"] == "get_song"
    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_result["tool_use_id"] == "tu-1"


def test_chat_turn_rejects_other_users_song(stranger_client, monkeypatch):
    c, factory = stranger_client
    stack = attach_cowriter_service(c, factory, monkeypatch, "u-spy")

    resp = c.post(
        "/api/chat/turn",
        json={"message": "spy", "current_song_id": "s1"},
    )

    assert resp.status_code == 404
    assert stack.agent.runs == []


def test_chat_turn_unexpected_error_emits_error_frame_and_marks_job_failed(client, service):
    c, factory = client
    service.agent.reply_with(fails_to_connect(RuntimeError("kaboom")))

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
        assert [(m.role, m.content) for m in session.query(ChatMessage)] == [("user", "oops")]


@pytest.mark.parametrize(
    ("next_message", "expected_history"),
    [
        ("oops", [("user", "oops"), ("assistant", "ok")]),
        ("never mind", [("user", "oops"), ("user", "never mind"), ("assistant", "ok")]),
    ],
    ids=["try-again-answers-the-kept-message", "a-new-message-follows-it"],
)
def test_a_turn_after_an_unanswered_one_keeps_the_message_it_left(
    client, service, next_message, expected_history,
):
    c, factory = client
    service.agent.reply_with(fails_to_connect(RuntimeError("kaboom")))
    c.post("/api/chat/turn", json={"message": "oops"})
    service.agent.reply_with(answers("ok"))

    final = _final_event(_stream_events(
        c.post("/api/chat/turn", json={"message": next_message}),
    ))

    assert final["user_message"]["content"] == next_message
    with factory() as session:
        messages = session.query(ChatMessage).order_by(ChatMessage.created_at).all()
        assert [(m.role, m.content) for m in messages] == expected_history


# ── /api/conversations ────────────────────────────────────────────────


def test_list_conversations_scoped_to_user(client):
    c, factory = client
    with factory() as session:
        session.add(Conversation(id="mine-1", user_id="u-test", title="mine"))
        session.add(User(
            id="u-other", username="other", role="user",
        ))
        session.flush()
        session.add(Conversation(id="not-mine", user_id="u-other", title="no"))
        session.commit()

    resp = c.get("/api/conversations")
    assert resp.status_code == 200
    ids = [conv["id"] for conv in resp.json()["conversations"]]
    assert ids == ["mine-1"]


def test_list_conversations_includes_counts(client, service):
    c, factory = client
    c.post("/api/chat/turn", json={"message": "a"})

    resp = c.get("/api/conversations")
    conv = resp.json()["conversations"][0]
    assert conv["message_count"] == 2
    assert conv["last_message_at"] is not None


def test_get_conversation_returns_messages(client, service):
    c, _ = client
    service.agent.reply_with(answers("reply!"))
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
            id="u-owner2", username="o", role="user",
        ))
        session.flush()
        session.add(Conversation(id="not-mine", user_id="u-owner2", title="x"))
        session.commit()
    resp = c.get("/api/conversations/not-mine")
    assert resp.status_code == 404


def test_get_conversation_404_when_unknown(client):
    c, _ = client
    assert c.get("/api/conversations/bogus").status_code == 404


def test_new_conversation_archives_active(client, service):
    c, factory = client
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


def test_delete_conversation_removes_messages(client, service):
    c, factory = client
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
            id="u-owner3", username="o", role="user",
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
