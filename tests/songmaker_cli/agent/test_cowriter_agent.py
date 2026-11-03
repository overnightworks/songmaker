"""The shipped agent file, the tools it selects and the backend composed at startup."""

from __future__ import annotations

import asyncio
from importlib.resources import files

import pytest
from agent_runtime_client.agents import load_agent
from agent_runtime_client.backend.gateway import GatewayBackend
from agent_runtime_client.tools import Principal
from fastapi import FastAPI
from support.cowriter_gateway import agent_config
from support.web_app import make_router_ctx

from songmaker_cli.agent.backend import compose_agent_backend
from songmaker_cli.agent.tools import cowriter_hand_tools, cowriter_tool_declarations
from songmaker_cli.cowriter.tools import COWRITER_TOOLS
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.settings import Settings

_PERSON_FIELDS = ("user", "owner", "created_by", "principal", "sub")


def test_the_shipped_agent_file_loads_and_selects_exactly_the_declared_tools():
    agent = load_agent(
        files("songmaker_cli") / "agents" / "cowriter.md", cowriter_tool_declarations(),
    )

    assert [tool.name for tool in agent.tools] == [tool.name for tool in COWRITER_TOOLS]


@pytest.mark.parametrize("declaration", cowriter_tool_declarations(), ids=lambda d: d.name)
def test_no_tool_schema_lets_the_model_name_a_person(declaration):
    assert not set(declaration.parameters["properties"]) & set(_PERSON_FIELDS)


def test_the_hand_tools_serve_exactly_the_declared_tools(tmp_path):
    hand_tools = cowriter_hand_tools(init_test_db(tmp_path / "tools.db"))

    assert [tool.declaration for tool in hand_tools] == cowriter_tool_declarations()


def _app(tmp_path) -> FastAPI:
    app = FastAPI()
    app.state.ctx = make_router_ctx(tmp_path, db=init_test_db(tmp_path / "composed.db"))
    return app


def test_an_unset_agent_composes_no_backend(tmp_path):
    app = _app(tmp_path)

    compose_agent_backend(app, Settings())

    assert app.state.agent_backend is None


def test_a_set_agent_composes_the_gateway_backend_once(tmp_path):
    app = _app(tmp_path)

    compose_agent_backend(app, Settings(agent=agent_config(tmp_path)))

    assert isinstance(app.state.agent_backend, GatewayBackend)


def test_a_hand_tool_for_an_unknown_person_is_refused_and_acts_for_nobody(tmp_path):
    hand_tools = cowriter_hand_tools(init_test_db(tmp_path / "tools.db"))
    list_albums = next(tool for tool in hand_tools if tool.declaration.name == "list_albums")

    outcome = asyncio.run(list_albums.handler(Principal(iss="issuer.test", sub="nobody"), {}))

    assert outcome.is_error is True
