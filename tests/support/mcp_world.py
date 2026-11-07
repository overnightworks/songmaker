"""The token world with the MCP endpoint on, and an agent's header-exact requests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from agent_runtime_client.mcp_wire import LATEST_PROTOCOL_VERSION as PROTOCOL_VERSION
from agent_runtime_client.mcp_wire import PROTOCOL_VERSION_HEADER as PROTOCOL_HEADER
from sqlalchemy.orm import sessionmaker
from support.token_world import TokenWorld, make_token_world
from support.web_app import seed_user

from songmaker_cli.constants import OIDC_LOGIN_GROUP, OIDC_MCP_GROUP
from songmaker_cli.db.models import Album, Song, Version

AGENTS_CLIENT = "agents"
MCP_SCOPE = "songmaker:mcp"
RESOURCE_URL = "https://songmaker.test/mcp"
METADATA_URL = "https://songmaker.test/.well-known/oauth-protected-resource/mcp"
AGENT_ENVIRONMENT = {
    "AGENT__BACKEND": "litellm",
    "AGENT__GATEWAY__ORIGIN": "http://gateway.test:4000",
    "AGENT__GATEWAY__KEY_FILE": "/run/secrets/gateway_key",
    "AGENT__API_GROUP": "/apps/songmaker/api",
}
AGENT_GROUP = "/agents"
MCP_CLIENT_ENVIRONMENT = {"AGENT__MCP_CLIENT_ID": AGENTS_CLIENT, "AGENT__MCP_SCOPE": MCP_SCOPE}
MCP_ENVIRONMENT = {**MCP_CLIENT_ENVIRONMENT, "AGENT__MCP_AGENT_GROUP": AGENT_GROUP}


@dataclass(frozen=True)
class ToolReply:
    http_status: int
    is_error: bool
    text: str

    def json(self) -> object:
        return json.loads(self.text)


@dataclass
class McpWorld:
    """The token world with the MCP endpoint on, and an agent's header-exact requests."""

    world: TokenWorld

    def agent_token(
        self,
        subject: str = TokenWorld.ALICE,
        *,
        groups: tuple[str, ...] = (OIDC_LOGIN_GROUP, OIDC_MCP_GROUP),
        **claims: object,
    ) -> str:
        return self.world.token(
            subject,
            groups=groups,
            **{"aud": RESOURCE_URL, "azp": AGENTS_CLIENT, "scope": MCP_SCOPE, **claims},
        )

    def agent(self, subject: str = TokenWorld.ALICE, **options: object) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.agent_token(subject, **options)}"}

    def rpc(self, method: str, params: dict | None = None, *, headers: dict[str, str]):
        message = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        return self.world.client.post(
            "/mcp", json=message, headers={**headers, PROTOCOL_HEADER: str(PROTOCOL_VERSION)},
        )

    def tool_names(self, **options: object) -> set[str]:
        reply = self.rpc("tools/list", headers=self.agent(**options))
        return {tool["name"] for tool in reply.json()["result"]["tools"]}

    def call(self, tool: str, arguments: dict | None = None, **options: object) -> ToolReply:
        reply = self.rpc(
            "tools/call", {"name": tool, "arguments": arguments or {}},
            headers=self.agent(**options),
        )
        result = reply.json()["result"]
        return ToolReply(reply.status_code, result.get("isError", False),
                         result["content"][0]["text"])

    def seed_people(self, *, alice_role: str = "user") -> None:
        with self.world.factory() as session:
            seed_user(session, "alice", alice_role, user_id=TokenWorld.ALICE)
            seed_user(session, "bob", user_id=TokenWorld.BOB)
            session.commit()

    def seed_song_without_lyrics(self, owner: str) -> str:
        with self.world.factory() as session:
            session.add(Album(id="album-bare", title="Bare", artist="", created_by=owner))
            session.add(Song(id="song-bare", title="Bare", album_id="album-bare",
                             track_number=1, slug="song-bare"))
            session.add(Version(id="version-bare", song_id="song-bare", version_number=1,
                                lyrics="", prompt=""))
            session.commit()
        return "song-bare"

    def rows_of(self, model: type, *columns: str) -> list[tuple]:
        return self.world.rows(model, *columns)


def build_mcp_world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    factory: sessionmaker,
    *,
    alice_role: str = "user",
    generation_limit: int = 30,
    mcp_environment: dict[str, str] | None = None,
) -> McpWorld:
    environment = {**AGENT_ENVIRONMENT, **(MCP_ENVIRONMENT if mcp_environment is None
                                           else mcp_environment)}
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GENERATION_RATE_LIMIT_USER", str(generation_limit))
    mcp_world = McpWorld(make_token_world(tmp_path, factory=factory))
    mcp_world.seed_people(alice_role=alice_role)
    return mcp_world


@pytest.fixture
def mcp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory) -> McpWorld:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    return build_mcp_world(tmp_path, monkeypatch, pg_factory)
