"""The shipped agent file, the tools it selects and the backend composed at startup."""

from __future__ import annotations

import asyncio
import json
from importlib.resources import files

import pytest
from agents.agent_file import load_agent
from agents.backend.gateway import GatewayBackend
from agents.tools import Principal
from fastapi import FastAPI
from support.admin_client import build_admin_client
from support.cowriter_gateway import agent_config, attach_cowriter_gateway, closed_port_origin
from support.realm import LOGIN_GROUP
from support.web_app import make_authenticated_user, make_router_ctx

from songmaker_cli.agent.backend import TurnCaller, compose_agent_backend, cover_admission
from songmaker_cli.agent.settings import AgentSettings
from songmaker_cli.agent.tools import cowriter_hand_tools, cowriter_tool_declarations
from songmaker_cli.api_models import AgentProblem
from songmaker_cli.cowriter.tools import COWRITER_TOOLS
from songmaker_cli.db.models import User
from songmaker_cli.settings import RealmSettings, Settings

_PERSON_FIELDS = ("user", "owner", "created_by", "principal", "sub")


def test_the_shipped_agent_file_loads_and_selects_exactly_the_declared_tools():
    """The one agent file selects exactly the tools the app declares."""
    agent = load_agent(
        files("songmaker_cli") / "agents" / "cowriter.md", cowriter_tool_declarations(),
    )

    assert [tool.name for tool in agent.tools] == [tool.name for tool in COWRITER_TOOLS]


@pytest.mark.parametrize("declaration", cowriter_tool_declarations(), ids=lambda d: d.name)
def test_no_tool_schema_lets_the_model_name_a_person(declaration):
    assert not set(declaration.parameters["properties"]) & set(_PERSON_FIELDS)


def test_the_hand_tools_serve_exactly_the_declared_tools(pg_factory):
    hand_tools = cowriter_hand_tools(pg_factory)

    assert [tool.declaration for tool in hand_tools] == cowriter_tool_declarations()


def _app(tmp_path, pg_factory) -> FastAPI:
    app = FastAPI()
    app.state.ctx = make_router_ctx(tmp_path, db=pg_factory)
    return app


def _agent_settings(directory) -> AgentSettings:
    gateway = agent_config(directory, origin=closed_port_origin()).gateway
    return AgentSettings(gateway=gateway)


def test_an_unset_agent_composes_no_backend_and_needs_no_ai_group(
    tmp_path, pg_factory, monkeypatch,
):
    monkeypatch.delenv("REALM_AI_GROUP")
    app = _app(tmp_path, pg_factory)

    compose_agent_backend(app, Settings(), RealmSettings())

    assert (app.state.agent_backend, app.state.agent_api_group) == (None, None)


def test_a_configured_gateway_without_the_ai_group_stops_composition_under_its_key(
    tmp_path, pg_factory, monkeypatch,
):
    monkeypatch.delenv("REALM_AI_GROUP")

    with pytest.raises(ValueError, match="REALM_AI_GROUP is required"):
        compose_agent_backend(
            _app(tmp_path, pg_factory),
            Settings(agent=_agent_settings(tmp_path)),
            RealmSettings(),
        )


def test_a_set_agent_composes_one_gateway_backend_that_serves_every_turn(tmp_path, pg_factory):
    client, factory = build_admin_client(
        tmp_path,
        lambda session: session.add(User(id="u-test", username="u-test", role="admin")),
        user_id="u-test",
        username="u-test",
        factory=pg_factory,
    )
    attach_cowriter_gateway(client, factory, tmp_path, "u-test")
    app = client.app
    compose_agent_backend(app, Settings(agent=_agent_settings(tmp_path)), RealmSettings())
    composed = app.state.agent_backend

    first = client.post("/api/chat/turn", json={"message": "hello"})
    second = client.post("/api/chat/turn", json={"message": "hello again"})

    assert isinstance(composed, GatewayBackend)
    assert app.state.agent_backend is composed
    assert [_problem_frame(first), _problem_frame(second)] == [(503, "unavailable")] * 2


@pytest.mark.parametrize(
    ("in_ai_group", "turn_problem", "cover_problem"),
    [
        (True, (503, "unavailable"), None),
        (False, (403, "not_enabled"), AgentProblem.NOT_ENABLED),
    ],
    ids=["inside-the-realm-ai-group", "outside-the-realm-ai-group"],
)
def test_the_group_a_caller_is_checked_against_is_the_realm_ai_group(
    tmp_path, pg_factory, in_ai_group, turn_problem, cover_problem,
):
    ai_group = "/services/litellm"
    groups = (LOGIN_GROUP, ai_group) if in_ai_group else (LOGIN_GROUP,)
    client, factory = build_admin_client(
        tmp_path,
        lambda session: session.add(User(id="u-test", username="u-test", role="admin")),
        user_id="u-test",
        username="u-test",
        factory=pg_factory,
    )
    stack = attach_cowriter_gateway(client, factory, tmp_path, "u-test", groups=groups)
    compose_agent_backend(
        client.app,
        Settings(agent=_agent_settings(tmp_path)),
        RealmSettings(REALM_AI_GROUP=ai_group),
    )

    turn = _problem_frame(client.post("/api/chat/turn", json={"message": "hello"}))
    admission = cover_admission(
        TurnCaller(client.app, stack.session_id, make_authenticated_user("u-test")),
    )

    assert turn == turn_problem
    assert getattr(admission, "problem", None) == cover_problem


def _problem_frame(response) -> tuple[int, str]:
    frames = [
        json.loads(line[len("data: "):])
        for line in response.iter_lines()
        if line.startswith("data: ")
    ]
    error = next(frame for frame in frames if frame.get("type") == "error")
    return error["status"], error["problem"]


def test_a_hand_tool_for_an_unknown_person_is_refused_and_acts_for_nobody(pg_factory):
    hand_tools = cowriter_hand_tools(pg_factory)
    list_albums = next(tool for tool in hand_tools if tool.declaration.name == "list_albums")

    outcome = asyncio.run(list_albums.handler(Principal(iss="issuer.test", sub="nobody"), {}))

    assert outcome.is_error is True
