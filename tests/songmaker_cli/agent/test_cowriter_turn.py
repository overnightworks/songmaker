"""A co-writer turn through the gateway backend, driven at ``POST /api/chat/turn``.

The gateway is ``FakeGateway``; songmaker's hand tools, the turn and the route are real.
"""

from __future__ import annotations

import json
import logging
import re
import socket
from dataclasses import dataclass
from pathlib import Path

import pytest
from agent_runtime_client.backend import TurnStopKind, TurnStopped
from agent_runtime_client.backend.fake_gateway import Reply, completion, tool_call, tool_round
from agent_runtime_client.backend.gateway import GatewayBackend
from agent_runtime_client.config import AgentConfig, ChatGateway
from agent_runtime_client.turn import FailureCode, RejectionCode
from fastapi.testclient import TestClient
from support.cowriter_gateway import (
    API_GROUP,
    CowriterStack,
    agent_config,
    attach_cowriter_gateway,
    stops,
)
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.agent.tools import cowriter_hand_tools
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, ChatMessage, Job, Song, User, Version

USER_ID = "u-test"
OTHER_SONG = "s-other"


@dataclass
class World:
    client: TestClient
    factory: object
    stack: CowriterStack
    tmp_path: Path

    def turn(self, message: str = "hey") -> list[dict]:
        response = self.client.post("/api/chat/turn", json={"message": message})
        assert response.status_code == 200
        return [
            json.loads(line[len("data: "):])
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]

    def stored_roles(self) -> list[str]:
        with self.factory() as session:
            return [m.role for m in session.query(ChatMessage).order_by(ChatMessage.created_at)]


def _seed(session) -> None:
    for owner, song_id in ((USER_ID, "s1"), ("u-other", OTHER_SONG)):
        session.add(User(id=owner, username=owner, role="user"))
        session.flush()
        session.add(Album(id=f"alb-{owner}", title="Rock", artist="B", created_by=owner))
        session.add(Song(id=song_id, title=f"Thunder {owner}", album_id=f"alb-{owner}",
                         track_number=1))
        session.add(Version(id=f"v-{song_id}", song_id=song_id, version_number=1,
                            lyrics="verse", prompt="rock", bpm=120, key_scale="Am",
                            audio_duration=180))
    session.commit()


def build_world(tmp_path: Path, *, role: str = "user", **attach) -> World:
    factory = init_test_db(tmp_path / "turn.db")
    with factory() as session:
        _seed(session)
    app = make_router_app(
        make_router_ctx(tmp_path, db=factory),
        user=make_authenticated_user(USER_ID, role=role),
    )
    client = web_client(app)
    stack = attach_cowriter_gateway(client, factory, tmp_path, USER_ID, **attach)
    return World(client, factory, stack, tmp_path)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return build_world(tmp_path)


def _frame(events: list[dict], kind: str) -> dict:
    return next(event for event in events if event["type"] == kind)


def _types(events: list[dict]) -> list[str]:
    return [event["type"] for event in events]


def test_a_turn_with_a_tool_round_streams_its_frames_and_stores_the_answer(world):
    world.stack.replies(
        tool_round(tool_call("call-1", "get_song", {"song_id": "s1"})),
        completion("It has one verse."),
    )

    events = world.turn("what does s1 hold")

    assert _types(events) == ["tool_call", "tool_result", "assistant_text", "final"]
    assert _frame(events, "tool_call")["name"] == "get_song"
    result = _frame(events, "tool_result")
    assert result["is_error"] is False
    assert "verse" in result["content"]
    assert _frame(events, "final")["assistant_message"]["content"] == "It has one verse."
    assert world.stored_roles() == ["user", "assistant"]
    with world.factory() as session:
        assert session.query(Job).filter_by(type="chat").one().status == "completed"


def test_a_tool_acts_only_for_the_turns_person_and_the_turn_goes_on(world):
    world.stack.replies(
        tool_round(tool_call("call-1", "get_song", {"song_id": OTHER_SONG})),
        completion("I cannot reach that song."),
    )

    events = world.turn("read the other song")

    result = _frame(events, "tool_result")
    assert result["is_error"] is True
    assert "u-other" not in result["content"]
    assert _frame(events, "final")["assistant_message"]["content"] == "I cannot reach that song."


def test_a_handler_that_raises_gives_the_model_a_fixed_sentence_and_logs_the_class(
    world, monkeypatch, caplog,
):
    def explode(*_arguments, **_keywords):
        raise RuntimeError("the secret detail")

    monkeypatch.setattr("songmaker_cli.agent.tools.execute_cowriter_tool", explode)
    world.stack.replies(
        tool_round(tool_call("call-1", "get_song", {"song_id": "s1"})),
        completion("That failed."),
    )

    with caplog.at_level(logging.ERROR):
        events = world.turn("read s1")

    result = _frame(events, "tool_result")
    assert result["is_error"] is True
    assert "secret detail" not in result["content"]
    assert "RuntimeError" in caplog.text
    assert "secret detail" not in caplog.text
    assert _frame(events, "final")["assistant_message"]["content"] == "That failed."


def _closed_port_origin() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{probe.getsockname()[1]}"


def _backend_without_key(world: World) -> GatewayBackend:
    config = AgentConfig(
        backend=world.stack.config.backend,
        gateway=ChatGateway(
            origin=world.stack.config.gateway.origin, key_file=world.tmp_path / "no-such-key",
        ),
        api_group=API_GROUP,
    )
    return GatewayBackend(config, tools=cowriter_hand_tools(world.factory), transport=None)


def _arrange_reply(world: World, arrangement: str) -> None:
    match arrangement:
        case "gateway-error":
            world.stack.replies(Reply(status=500))
        case "budget-refusal":
            world.stack.replies(Reply(status=400, body=b'{"error": {"message": "Budget"}}'))
        case "no-words-after-a-tool-round":
            world.stack.replies(
                tool_round(tool_call("call-1", "get_song", {"song_id": "s1"})),
                completion("   "),
            )
        case "refused-connection":
            config = agent_config(world.tmp_path, origin=_closed_port_origin())
            world.stack.app.state.agent_backend = GatewayBackend(
                config, tools=cowriter_hand_tools(world.factory),
            )
        case "missing-key-file":
            world.stack.app.state.agent_backend = _backend_without_key(world)
        case "tool-calls-crossed" | "deadline-passed":
            world.stack.behaves(stops(TurnStopped(TurnStopKind.FAILED, FailureCode.LIMIT_EXCEEDED)))
        case "cancelled":
            world.stack.behaves(stops(TurnStopped(TurnStopKind.CANCELLED)))
        case "refused-for-another-reason":
            world.stack.behaves(
                stops(TurnStopped(TurnStopKind.REFUSED, RejectionCode.UNAVAILABLE)),
            )


@pytest.mark.parametrize(
    "arrangement",
    [
        "gateway-error", "budget-refusal", "no-words-after-a-tool-round", "refused-connection",
        "missing-key-file", "tool-calls-crossed", "deadline-passed", "cancelled",
        "refused-for-another-reason",
    ],
)
def test_a_turn_the_gateway_cannot_finish_ends_unavailable_and_stores_no_answer(
    world, arrangement,
):
    _arrange_reply(world, arrangement)

    events = world.turn()

    problem = _frame(events, "error")
    assert (problem["status"], problem["problem"]) == (503, "unavailable")
    assert _types(events)[-1] == "error"
    assert world.stored_roles() == ["user"]
    with world.factory() as session:
        assert session.query(Job).filter_by(type="chat").one().status == "failed"


def test_a_busy_gateway_reads_busy_with_the_wait_it_named(world):
    world.stack.replies(Reply(status=429, headers={"Retry-After": "7"}))

    problem = _frame(world.turn(), "error")

    assert (problem["status"], problem["problem"], problem["retry_after_seconds"]) == (
        429, "busy", 7,
    )
    assert world.stored_roles() == ["user"]


@pytest.mark.parametrize(
    ("role", "groups"),
    [("user", ("/apps/songmaker",)), ("guest", ("/apps/songmaker", API_GROUP))],
    ids=["outside-the-api-group", "role-outside-the-agents-roles"],
)
def test_a_person_the_agent_is_not_enabled_for_is_refused_and_no_request_leaves(
    tmp_path, role, groups,
):
    world = build_world(tmp_path, role=role, groups=groups)

    problem = _frame(world.turn(), "error")

    assert (problem["status"], problem["problem"]) == (403, "not_enabled")
    assert world.stack.gateway_requests == []
    assert world.stored_roles() == ["user"]


@pytest.mark.parametrize("arrangement", ["no-refresh-token", "refresh-grant-refused"])
def test_a_session_without_a_usable_refresh_grant_signs_in_again_and_no_request_leaves(
    tmp_path, arrangement,
):
    world = build_world(
        tmp_path, refresh_token=None if arrangement == "no-refresh-token" else "stale-token",
    )
    world.stack.issuer.refuses_refresh_with = (
        "invalid_grant" if arrangement == "refresh-grant-refused" else None
    )

    problem = _frame(world.turn(), "error")

    assert (problem["status"], problem["problem"]) == (401, "sign_in_again")
    assert world.stack.gateway_requests == []


def test_the_issuer_being_down_ends_the_turn_unavailable_and_no_request_leaves(world):
    world.stack.issuer.unreachable = True

    problem = _frame(world.turn(), "error")

    assert (problem["status"], problem["problem"]) == (503, "unavailable")
    assert world.stack.gateway_requests == []


def test_an_unset_agent_ends_the_turn_unavailable_without_a_request(world):
    world.stack.app.state.agent_backend = None

    problem = _frame(world.turn(), "error")

    assert (problem["status"], problem["problem"]) == (503, "unavailable")
    assert world.stack.gateway_requests == []


def test_a_refused_agent_file_ends_the_turn_unavailable_and_is_logged(world, monkeypatch, caplog):
    from agent_runtime_client.agents import AgentFileError

    from songmaker_cli.agent import backend

    def refuse(*_arguments):
        raise AgentFileError("cowriter.md: model: refused")

    backend._cowriter_agent.cache_clear()
    monkeypatch.setattr(backend, "load_agent", refuse)
    try:
        with caplog.at_level(logging.ERROR):
            problem = _frame(world.turn(), "error")
    finally:
        backend._cowriter_agent.cache_clear()

    assert (problem["status"], problem["problem"]) == (503, "unavailable")
    assert "agent file" in caplog.text
    assert world.stack.gateway_requests == []


_FINGERPRINT = re.compile(r"fp-[0-9a-f]{64}")


def _user_field_of_a_turn(tmp_path: Path, monkeypatch, issuer: str) -> tuple[str, bytes]:
    from songmaker_cli.settings import get_settings

    monkeypatch.setenv("OIDC_ISSUER", issuer)
    get_settings.cache_clear()
    turn_world = build_world(tmp_path)
    turn_world.stack.issuer.token_issuer = issuer.rstrip("/")
    turn_world.turn()
    request = turn_world.stack.gateway_requests[0]
    return json.loads(request.content)["user"], request.content


def test_the_request_names_the_person_only_by_a_fingerprint_of_issuer_and_id(
    tmp_path, monkeypatch, fresh_settings,
):
    bare, bare_body = _user_field_of_a_turn(tmp_path / "bare", monkeypatch, "https://issuer.test/realms/test")
    slashed, slashed_body = _user_field_of_a_turn(
        tmp_path / "slashed", monkeypatch, "https://issuer.test/realms/test/",
    )

    assert _FINGERPRINT.fullmatch(bare)
    assert bare == slashed
    for body in (bare_body, slashed_body):
        assert USER_ID.encode() not in body
        assert b"issuer.test" not in body


@pytest.mark.parametrize("answers", [True, False], ids=["an-answer", "a-problem"])
def test_a_turn_read_to_its_end_holds_exactly_one_terminal_outcome_last(world, answers):
    import asyncio

    from agent_runtime_client.turn import TurnMessage

    from songmaker_cli.agent.backend import TurnAnswer, TurnCaller, TurnProblem, run_cowriter_turn

    if not answers:
        world.stack.app.state.agent_backend = None
    caller = TurnCaller(
        world.client.app, world.stack.session_id, make_authenticated_user(USER_ID),
    )

    async def read_to_the_end():
        messages = [TurnMessage(role="user", text="hey")]
        return [outcome async for outcome in run_cowriter_turn(caller, messages)]

    outcomes = asyncio.run(read_to_the_end())

    terminal = TurnAnswer if answers else TurnProblem
    assert [isinstance(outcome, terminal) for outcome in outcomes].count(True) == 1
    assert isinstance(outcomes[-1], terminal)
