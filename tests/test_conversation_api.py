"""Tests for the Phase 3 co-writer endpoints + the MCP-enabled Claude call."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from conftest import TEST_SECRET, make_fake_redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import (
    Album,
    AvailableModel,
    ChatMessage,
    Conversation,
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
    response = MagicMock()
    response.text = text
    return AsyncMock(return_value=response)


# ── provider: _build_mcp_cli_cmd ──────────────────────────────────────


def test_mcp_cli_cmd_includes_required_flags():
    from songmaker_cli.claude.provider import (
        MCP_ALLOWED_TOOLS,
        _build_mcp_cli_cmd,
    )

    cmd = _build_mcp_cli_cmd(
        "claude", "hi", "sysprompt", "claude-opus-4-6", "user-1",
    )
    assert "--mcp-config" in cmd
    assert "--strict-mcp-config" in cmd
    assert "--allowedTools" in cmd
    assert MCP_ALLOWED_TOOLS in cmd
    assert "--permission-mode" in cmd
    assert "bypassPermissions" in cmd
    assert "--system-prompt" in cmd
    assert "sysprompt" in cmd


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
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(
            return_value=(b'{"result":"ok"}', b""),
        )
        return proc

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec", fake_exec,
    )

    result = asyncio.run(provider.acall_claude_with_mcp(
        prompt="hi", user_id="u-1", model="claude-opus-4-6",
    ))
    assert result.text == "ok"
    assert "--mcp-config" in captured["cmd"]
    # Sanity check that parent env is scrubbed before exec.
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
        proc.returncode = 0
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

        def _kill():
            killed["value"] = True
        proc.kill = _kill
        proc.wait = AsyncMock(return_value=None)
        return proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    with pytest.raises(provider.UnavailableError):
        asyncio.run(provider.acall_claude_with_mcp(
            prompt="hi", user_id="u-1", timeout_seconds=1,
        ))
    assert killed["value"] is True


# ── /api/chat/turn ────────────────────────────────────────────────────


def test_chat_turn_creates_active_conversation_and_stores_messages(client):
    c, factory = client
    mock_acall = _mock_claude("ok")
    with patch("songmaker_cli.conversation_api.acall_claude_with_mcp", mock_acall):
        resp = c.post("/api/chat/turn", json={"message": "hey"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_message"]["content"] == "hey"
    assert body["assistant_message"]["content"] == "ok"
    conv_id = body["conversation_id"]

    with factory() as session:
        convs = session.query(Conversation).all()
        assert len(convs) == 1
        assert convs[0].id == conv_id
        assert convs[0].user_id == "u-test"
        assert convs[0].archived_at is None
        msgs = session.query(ChatMessage).order_by(ChatMessage.created_at).all()
        assert [m.role for m in msgs] == ["user", "assistant"]
        assert all(m.conversation_id == conv_id for m in msgs)


def test_chat_turn_reuses_active_conversation_across_turns(client):
    c, factory = client
    mock_acall = _mock_claude()
    with patch("songmaker_cli.conversation_api.acall_claude_with_mcp", mock_acall):
        r1 = c.post("/api/chat/turn", json={"message": "one"})
        r2 = c.post("/api/chat/turn", json={"message": "two"})
    assert r1.json()["conversation_id"] == r2.json()["conversation_id"]
    with factory() as session:
        assert session.query(Conversation).count() == 1
        assert session.query(ChatMessage).count() == 4


def test_chat_turn_injects_current_song_block(client):
    c, _ = client
    mock_acall = _mock_claude()
    with patch(
        "songmaker_cli.conversation_api.acall_claude_with_mcp", mock_acall,
    ):
        resp = c.post(
            "/api/chat/turn",
            json={"message": "rewrite the chorus", "current_song_id": "s1"},
        )
    assert resp.status_code == 200
    last_call = mock_acall.await_args
    messages = last_call.kwargs["messages"]
    last_user = messages[-1]["content"]
    assert "<current_song>" in last_user
    assert "title: Thunder" in last_user
    assert "lyrics:\nverse" in last_user
    # Claude sees the current song even though we only pass user_id to the MCP.
    assert last_call.kwargs["user_id"] == "u-test"


def test_chat_turn_rejects_other_users_song(stranger_client):
    c, _ = stranger_client
    mock_acall = _mock_claude()
    with patch(
        "songmaker_cli.conversation_api.acall_claude_with_mcp", mock_acall,
    ):
        resp = c.post(
            "/api/chat/turn",
            json={"message": "spy", "current_song_id": "s1"},
        )
    assert resp.status_code == 404
    # Claude must not have been called for an unauthorized song.
    mock_acall.assert_not_awaited()


def test_chat_turn_unexpected_error_marks_job_failed(client):
    c, factory = client
    mock_acall = AsyncMock(side_effect=RuntimeError("kaboom"))
    with (
        patch("songmaker_cli.conversation_api.acall_claude_with_mcp", mock_acall),
        pytest.raises(Exception),
    ):
        c.post("/api/chat/turn", json={"message": "oops"})

    with factory() as session:
        from songmaker_cli.db.models import Job

        jobs = session.query(Job).all()
        assert len(jobs) == 1
        assert jobs[0].status == "failed"


def test_chat_turn_failure_leaves_no_empty_conversation(client):
    c, factory = client
    from songmaker_cli.claude.provider import UnavailableError

    mock_acall = AsyncMock(side_effect=UnavailableError("down"))
    with patch(
        "songmaker_cli.conversation_api.acall_claude_with_mcp", mock_acall,
    ):
        resp = c.post("/api/chat/turn", json={"message": "hi"})
    assert resp.status_code == 503

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
    mock_acall = _mock_claude()
    with patch(
        "songmaker_cli.conversation_api.acall_claude_with_mcp", mock_acall,
    ):
        c.post("/api/chat/turn", json={"message": "a"})

    resp = c.get("/api/conversations")
    conv = resp.json()["conversations"][0]
    assert conv["message_count"] == 2
    assert conv["last_message_at"] is not None


def test_get_conversation_returns_messages(client):
    c, _ = client
    mock_acall = _mock_claude("reply!")
    with patch(
        "songmaker_cli.conversation_api.acall_claude_with_mcp", mock_acall,
    ):
        turn = c.post("/api/chat/turn", json={"message": "question?"})
    conv_id = turn.json()["conversation_id"]

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
    mock_acall = _mock_claude()
    with patch(
        "songmaker_cli.conversation_api.acall_claude_with_mcp", mock_acall,
    ):
        turn = c.post("/api/chat/turn", json={"message": "hi"})
    old_id = turn.json()["conversation_id"]

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
    mock_acall = _mock_claude()
    with patch(
        "songmaker_cli.conversation_api.acall_claude_with_mcp", mock_acall,
    ):
        turn = c.post("/api/chat/turn", json={"message": "bye"})
    conv_id = turn.json()["conversation_id"]

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
