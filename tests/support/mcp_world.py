"""The token world with the MCP endpoint on, and an agent's header-exact requests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
from agent_runtime_client.mcp_wire import PROTOCOL_VERSION
from agent_runtime_client.mcp_wire import PROTOCOL_VERSION_HEADER as PROTOCOL_HEADER
from mcp.shared.inbound import MCP_METHOD_HEADER, MCP_NAME_HEADER, NAME_BEARING_METHODS
from mcp_types import CLIENT_CAPABILITIES_META_KEY, PROTOCOL_VERSION_META_KEY
from sqlalchemy.orm import sessionmaker
from support.reference_rows import a_reference
from support.token_world import TokenWorld, make_token_world
from support.wav_files import write_wav
from support.web_app import seed_user

from songmaker_cli.constants import (
    OIDC_LOGIN_GROUP,
    OIDC_MCP_GROUP,
    LoraStatus,
    SongWorkKind,
)
from songmaker_cli.db.models import (
    Album,
    Base,
    Conversation,
    Generation,
    GenerationPreset,
    Job,
    Playlist,
    Song,
    UserLora,
    UserLoraSample,
    Version,
)
from songmaker_cli.db.queries.activity import record_song_edit, record_song_played

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
        envelope = {
            PROTOCOL_VERSION_META_KEY: PROTOCOL_VERSION,
            CLIENT_CAPABILITIES_META_KEY: {},
        }
        message = {
            "jsonrpc": "2.0", "id": 1, "method": method,
            "params": {**(params or {}), "_meta": envelope},
        }
        mirrored = {MCP_METHOD_HEADER: method}
        if method in NAME_BEARING_METHODS:
            mirrored[MCP_NAME_HEADER] = message["params"][NAME_BEARING_METHODS[method]]
        return self.world.client.post(
            "/mcp", json=message,
            headers={**headers, **mirrored, PROTOCOL_HEADER: str(PROTOCOL_VERSION)},
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

    def seed_household(self, owner: str, name: str) -> None:
        """One of each thing a person owns, keyed by ``name``, beside the take of ``seed_take``.

        The take is picked and has real audio, the song a recorded edit and listen, the LoRA
        three trainable samples; ``album-gone-<name>`` and ``song-gone-<name>`` are in the trash.
        """
        take_id = self.world.seed_take(owner, name)
        for suffix in ("wav", "mp3"):
            write_wav(self.world.audio_dir / owner / f"{name}.{suffix}", np.zeros(800), 8000)
        with self.world.factory() as session:
            take = session.get(Generation, take_id)
            take.wav_path = f"{owner}/{name}.wav"
            take.is_picked = True
            session.add(Album(id=f"album-gone-{name}", title=f"Gone {name}", artist="",
                              created_by=owner, deleted_at=datetime.now(timezone.utc)))
            session.add(Song(id=f"song-gone-{name}", title=f"Gone song {name}",
                             album_id=f"album-{name}", track_number=2, slug=f"song-gone-{name}",
                             deleted_at=datetime.now(timezone.utc)))
            record_song_edit(session, user_id=owner, song_id=f"song-{name}",
                             kind=SongWorkKind.CREATED)
            record_song_played(session, user_id=owner, song_id=f"song-{name}",
                               in_playlist=False)
            session.add(Playlist(id=f"playlist-{name}", title=f"Playlist {name}",
                                 slug=f"playlist-{name}", created_by=owner))
            session.add(GenerationPreset(id=f"preset-{name}", name=f"Preset {name}",
                                         model_mode="sft", params={}, created_by=owner))
            session.add(Conversation(id=f"conversation-{name}", user_id=owner,
                                     title=f"Conversation {name}"))
            session.add(Job(id=f"job-{name}", type="chat", status="queued", user_id=owner,
                            song_id=f"song-{name}"))
            a_reference(session, owner, name=f"{name}.wav", reference_id=f"reference-{name}")
            lora = UserLora(id=f"lora-{name}", user_id=owner, name=f"Lora {name}",
                            slug=f"lora-{name}", status=LoraStatus.DRAFT)
            session.add(lora)
            session.flush()
            for position in range(3):
                session.add(UserLoraSample(
                    id=f"sample-{name}-{position}", user_lora_id=lora.id,
                    audio_path=f"{name}/{position}.wav", caption="caption", lyrics="lyrics",
                    position=position,
                ))
            session.commit()

    def snapshot(self) -> dict[str, list[str]]:
        """Every row of every table, to prove a refused call wrote nothing."""
        with self.world.factory() as session:
            return {
                table.name: sorted(repr(tuple(row)) for row in session.execute(table.select()))
                for table in Base.metadata.sorted_tables
            }


def build_mcp_world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    factory: sessionmaker,
    lifespans: ExitStack,
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
    lifespans.enter_context(mcp_world.world.client)
    mcp_world.seed_people(alice_role=alice_role)
    return mcp_world


@contextmanager
def worker_ready() -> Iterator[AsyncMock]:
    """The generation, scoring and training workers answer healthy; yields the queue pool."""
    pool = AsyncMock()
    with (
        patch("songmaker_cli.generation_api.get_arq_pool", return_value=pool),
        patch("songmaker_cli.lora_api.get_arq_pool", return_value=pool),
        patch("songmaker_cli.generation_api.is_music_worker_healthy",
              AsyncMock(return_value=True)),
        patch("songmaker_cli.generation_api.is_scoring_worker_healthy",
              AsyncMock(return_value=True)),
        patch("songmaker_cli.generation_api._has_online_acestep_worker",
              AsyncMock(return_value=True)),
    ):
        yield pool


@pytest.fixture
def lifespans(mock_arq_pool) -> Iterator[ExitStack]:
    """Owns the app lifespans a world enters, so each ends with its test."""
    with ExitStack() as stack:
        yield stack


@pytest.fixture
def mcp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory, lifespans: ExitStack,
) -> McpWorld:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    return build_mcp_world(tmp_path, monkeypatch, pg_factory, lifespans)
