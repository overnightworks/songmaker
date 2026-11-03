"""The gateway and the realm behind a co-writer turn, as one in-process stand-in.

``attach_cowriter_gateway`` gives a test app what a deployed web has around the turn: a signed-in
session that holds a refresh token, a Keycloak that renews it and names the person's groups, and
a ``GatewayBackend`` over songmaker's own hand tools whose only fake is the gateway transport
(``FakeGateway``). ``ScriptedBackend`` replaces the backend where a test needs a turn the gateway
cannot script: one held open, one that raises, one that stops short.
"""

from __future__ import annotations

import socket
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from agent_runtime_client.agents import TurnRequest
from agent_runtime_client.backend import AgentBackend, TurnEvent, TurnPerson, TurnStopped
from agent_runtime_client.backend.fake_gateway import FakeGateway, Reply, completion
from agent_runtime_client.backend.gateway import GatewayBackend
from agent_runtime_client.config import AgentConfig, BackendKind, ChatGateway
from agent_runtime_client.turn_events import AssistantTextEvent, FinalEvent
from fake_oidc_issuer import FakeIssuer, Person, a_fake_issuer
from support.web_app import issued_cookies

from songmaker_cli.agent.tools import cowriter_hand_tools

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

API_GROUP = "/apps/songmaker/api"
A_REFRESH_TOKEN = "fake-refresh-token"  # noqa: S105
GATEWAY_ORIGIN = "http://gateway.test:4000"
_KEY_FILE_NAME = "gateway.key"
_DUMMY_KEY = "dummy-key-for-tests"
MEMBER_GROUPS = ("/apps/songmaker", API_GROUP)

Behavior = Callable[[TurnRequest, TurnPerson], AsyncGenerator[TurnEvent, None]]


def agent_config(directory: Path, *, origin: str = GATEWAY_ORIGIN) -> AgentConfig:
    """The ``agent`` setting for a gateway at ``origin``, its dummy key written in ``directory``."""
    key_file = directory / _KEY_FILE_NAME
    key_file.write_text(_DUMMY_KEY + "\n", encoding="ascii")
    return AgentConfig(
        backend=BackendKind.LITELLM,
        gateway=ChatGateway(origin=origin, key_file=key_file),
        api_group=API_GROUP,
    )


def closed_port_origin() -> str:
    """An origin on this machine where nothing listens, so a connection to it is refused."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{probe.getsockname()[1]}"


class ScriptedBackend:
    """An ``AgentBackend`` whose turn is a test's own async generator."""

    def __init__(self, behavior: Behavior) -> None:
        self.run = behavior


def held_until(release, text: str) -> Behavior:
    """Say a first word, wait for ``release``, then finish with ``text``."""

    async def run(_request: TurnRequest, _person: TurnPerson) -> AsyncGenerator[TurnEvent, None]:
        yield AssistantTextEvent(text="working on it")
        await release.wait()
        yield FinalEvent(text=text)

    return run


def raises(error: Exception) -> Behavior:
    async def run(_request: TurnRequest, _person: TurnPerson) -> AsyncGenerator[TurnEvent, None]:
        raise error
        yield  # makes this an async generator

    return run


def stops(stopped: TurnStopped) -> Behavior:
    return raises(stopped)


@dataclass(frozen=True)
class RecordedTurn:
    """One turn as the backend received it."""

    request: TurnRequest
    person: TurnPerson

    @property
    def messages(self) -> list[dict[str, str]]:
        return [
            {"role": message.role.value, "text": message.text}
            for message in self.request.turn.messages
        ]


class _RecordingBackend:
    def __init__(self, inner: AgentBackend, turns: list[RecordedTurn]) -> None:
        self._inner = inner
        self._turns = turns

    async def run(
        self, request: TurnRequest, person: TurnPerson
    ) -> AsyncGenerator[TurnEvent, None]:
        self._turns.append(RecordedTurn(request, person))
        async with aclosing(self._inner.run(request, person)) as events:
            async for event in events:
                yield event


@dataclass
class CowriterStack:
    app: object
    issuer: FakeIssuer
    session_id: str
    config: AgentConfig
    turns: list[RecordedTurn] = field(default_factory=list)
    gateways: list[FakeGateway] = field(default_factory=list)

    @property
    def last_turn(self) -> RecordedTurn:
        return self.turns[-1]

    @property
    def gateway_requests(self) -> list:
        return [request for gateway in self.gateways for request in gateway.requests]

    def replies(self, *replies: Reply) -> FakeGateway:
        """Answer the following gateway requests with ``replies`` (the last one repeats)."""
        gateway = FakeGateway(*replies)
        self.gateways.append(gateway)
        backend = GatewayBackend(
            self.config,
            tools=cowriter_hand_tools(self.app.state.ctx.db),
            transport=gateway,
        )
        self.app.state.agent_backend = _RecordingBackend(backend, self.turns)
        return gateway

    def behaves(self, behavior: Behavior) -> None:
        """Run the following turns as ``behavior`` instead of through a gateway."""
        self.app.state.agent_backend = _RecordingBackend(ScriptedBackend(behavior), self.turns)


def attach_cowriter_gateway(
    client: TestClient,
    factory,
    directory: Path,
    user_id: str,
    *,
    refresh_token: str | None = A_REFRESH_TOKEN,
    groups: tuple[str, ...] = MEMBER_GROUPS,
) -> CowriterStack:
    """Wire a test app so ``POST /chat/turn`` runs through a gateway that answers "ok".

    The client leaves signed in as ``user_id`` with a session that holds ``refresh_token``, and
    the realm names ``groups`` for that person at every renewal.
    """
    from pydantic import SecretStr
    from webauth.config import installed_web_auth_config

    from songmaker_cli.auth_stores import DatabaseSessionRecordStore

    app = client.app
    issuer = a_fake_issuer()
    issuer.person = Person(subject=user_id, groups=groups)
    app.state.oidc_sign_in = issuer.relying_party_for_app()

    config = installed_web_auth_config(app)
    now = datetime.now(timezone.utc)
    with factory() as session:
        record = DatabaseSessionRecordStore(session).create(
            user_id,
            now=now,
            expires_at=now + timedelta(seconds=config.session_lifetime.idle_seconds),
            refresh_token=None if refresh_token is None else SecretStr(refresh_token),
            id_token=None,
        )
        session.commit()
        session_id = record.id
    for name, value in issued_cookies(session_id, config).items():
        client.cookies.set(name, value)
    stack = CowriterStack(app, issuer, session_id, agent_config(directory))
    stack.replies(completion("ok"))
    return stack


def signed_in_request(client: TestClient):
    """A request that carries the client's cookies, for tests that call an endpoint directly."""
    from starlette.requests import Request

    cookie_header = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
    return Request({
        "type": "http",
        "app": client.app,
        "headers": [(b"cookie", cookie_header.encode())],
    })
