"""The agent service and the realm behind a co-writer turn, as one in-process stand-in.

``attach_cowriter_service`` gives a test app what a deployed web has around the turn: the
``/mcp`` verdict, a Keycloak that renews and issues workload tokens, a signed-in session that
holds a refresh token, and an agent service answering ``POST /runs``. The run client, the token
steps and the relay stay real; only the two outbound HTTP edges are replaced.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import httpx
from agent_runtime_client.sse import encode_event
from agent_runtime_client.tools import ToolEffect
from agent_runtime_client.wire import (
    AssistantText,
    Cancelled,
    Failed,
    FailureCode,
    Heartbeat,
    Offer,
    OfferedModel,
    OfferReason,
    OfferRoute,
    RejectionCode,
    RunRejection,
    RunStarted,
    Succeeded,
    ToolCall,
    ToolResult,
)
from conftest import apply_csrf_header, issued_cookies
from fake_oidc_issuer import FakeIssuer, a_fake_issuer

from songmaker_cli.cowriter import service_offer, service_turn
from songmaker_cli.cowriter.mcp_endpoint import AVAILABILITY_ATTRIBUTE, McpEndpointAvailability

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

SERVICE_URL = "http://agent-service.test:8080"
A_REFRESH_TOKEN = "fake-refresh-token"  # noqa: S105
PROTOCOL_VERSION = 2
HEARTBEAT_SECONDS = 15


@dataclass(frozen=True)
class RecordedRun:
    """One ``POST /runs`` as the service received it."""

    url: str
    headers: httpx.Headers
    body: dict[str, Any]

    @property
    def messages(self) -> list[dict[str, str]]:
        return self.body["turn"]["messages"]

    @property
    def system(self) -> str:
        return self.body["turn"]["system"]


class RunScript:
    """The frames of one run, numbered in order."""

    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = uuid.UUID(run_id) if run_id else uuid.uuid4()
        self._next_seq = 0

    def _common(self) -> dict[str, Any]:
        seq, self._next_seq = self._next_seq, self._next_seq + 1
        return {"v": PROTOCOL_VERSION, "run_id": self.run_id, "seq": seq}

    def started(self) -> bytes:
        return encode_event(RunStarted(**self._common(), heartbeat_interval_s=HEARTBEAT_SECONDS))

    def text(self, text: str) -> bytes:
        return encode_event(AssistantText(**self._common(), text=text))

    def heartbeat(self) -> bytes:
        return encode_event(Heartbeat(**self._common()))

    def tool_call(
        self, tool_use_id: str, name: str, arguments: dict[str, Any], *, writes: bool = False,
    ) -> bytes:
        effect = ToolEffect.SIDE_EFFECTING if writes else ToolEffect.READ_ONLY
        return encode_event(ToolCall(
            **self._common(), tool_use_id=tool_use_id, name=name, input=arguments, effect=effect,
        ))

    def tool_result(self, tool_use_id: str, content: str, *, is_error: bool = False) -> bytes:
        return encode_event(ToolResult(
            **self._common(), tool_use_id=tool_use_id, content=content, is_error=is_error,
        ))

    def succeeded(self, text: str) -> bytes:
        return encode_event(Succeeded(**self._common(), text=text))

    def failed(self, code: FailureCode, message: str = "The run failed.") -> bytes:
        return encode_event(Failed(**self._common(), code=code, message=message))

    def cancelled(self) -> bytes:
        return encode_event(Cancelled(**self._common()))


Frames = Callable[[RecordedRun, RunScript], AsyncIterator[bytes]]
Behavior = Callable[[RecordedRun], Awaitable[httpx.Response]]


class _FrameStream(httpx.AsyncByteStream):
    def __init__(self, frames: AsyncIterator[bytes]) -> None:
        self._frames = frames

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for frame in self._frames:
            yield frame

    async def aclose(self) -> None:
        await self._frames.aclose()  # type: ignore[attr-defined]


def streams(frames: Frames, *, run_id: str | None = None) -> Behavior:
    """A 200 whose body is the frames the callback yields, one chunk each, for run ``run_id``."""

    async def respond(run: RecordedRun) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_FrameStream(frames(run, RunScript(run_id))),
        )

    return respond


def answers(text: str, *, run_id: str | None = None, cut: bool = False) -> Behavior:
    """Start, say ``text`` and succeed with it; ``cut`` ends the stream before the terminal."""

    async def frames(_run: RecordedRun, script: RunScript) -> AsyncIterator[bytes]:
        yield script.started()
        yield script.text(text)
        if not cut:
            yield script.succeeded(text)

    return streams(frames, run_id=run_id)


def held_until(
    release: asyncio.Event, text: str, *, run_id: str | None = None,
) -> Behavior:
    """Say a first word, wait for ``release``, then succeed with ``text``."""

    async def frames(_run: RecordedRun, script: RunScript) -> AsyncIterator[bytes]:
        yield script.started()
        yield script.text("working on it")
        await release.wait()
        yield script.succeeded(text)

    return streams(frames, run_id=run_id)


def refuses(
    status: int, code: RejectionCode, *, retry_after_seconds: int | None = None,
) -> Behavior:
    """The typed refusal the service answers instead of a stream."""

    async def respond(_run: RecordedRun) -> httpx.Response:
        body = RunRejection(v=PROTOCOL_VERSION, code=code, message="Refused.").model_dump_json()
        headers = {"content-type": "application/json"}
        if retry_after_seconds is not None:
            headers["retry-after"] = str(retry_after_seconds)
        return httpx.Response(status, headers=headers, content=body)

    return respond


def fails_to_connect(error: Exception) -> Behavior:
    async def respond(_run: RecordedRun) -> httpx.Response:
        raise error

    return respond


OfferBehavior = Callable[[httpx.Request], Awaitable[httpx.Response]]


@dataclass(frozen=True)
class RecordedOfferRequest:
    """One ``GET /offer`` as the service received it."""

    url: str
    headers: httpx.Headers


def offered_model(model_id: str, *, ready: bool = True) -> OfferedModel:
    return OfferedModel(
        id=model_id, object="model", created=0, owned_by="agent-service", route=OfferRoute.CLI,
        background=True, ready=ready, reason=None if ready else OfferReason.NOT_BUILT,
    )


def offers(*models: OfferedModel) -> OfferBehavior:
    """A 200 whose body lists ``models``."""

    async def respond(_request: httpx.Request) -> httpx.Response:
        body = Offer(v=PROTOCOL_VERSION, object="list", data=list(models)).model_dump_json()
        return httpx.Response(200, headers={"content-type": "application/json"}, content=body)

    return respond


def answers_offer_with(status: int, content: bytes, *, content_type: str) -> OfferBehavior:
    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"content-type": content_type}, content=content)

    return respond


def refuses_offer(status: int, code: RejectionCode) -> OfferBehavior:
    body = RunRejection(v=PROTOCOL_VERSION, code=code, message="Refused.").model_dump_json()
    return answers_offer_with(status, body.encode(), content_type="application/json")


def never_answers_offer(longest_read_seconds: float) -> OfferBehavior:
    """The connection opens and nothing comes back: the request's own read timeout fires.

    The in-process transport enforces no timeouts, so the stand-in asserts that the caller set a
    read timeout of at most ``longest_read_seconds`` on the request and then raises the error
    the real transport raises when it expires.
    """

    async def respond(request: httpx.Request) -> httpx.Response:
        read_timeout = request.extensions["timeout"]["read"]
        assert read_timeout is not None
        assert read_timeout <= longest_read_seconds
        raise httpx.ReadTimeout("nothing came back", request=request)

    return respond


def offer_fails_to_connect(error: Exception) -> OfferBehavior:
    async def respond(_request: httpx.Request) -> httpx.Response:
        raise error

    return respond


@dataclass
class FakeAgentService:
    """Answers ``POST /runs`` with ``behavior`` and ``GET /offer`` with ``offer_behavior``.

    ``runs`` and ``offer_requests`` hold every request it received.
    """

    behavior: Behavior = field(default_factory=lambda: answers("ok"))
    runs: list[RecordedRun] = field(default_factory=list)
    offer_behavior: OfferBehavior = field(
        default_factory=lambda: offers(offered_model("claude/opus")),
    )
    offer_requests: list[RecordedOfferRequest] = field(default_factory=list)

    @property
    def last_run(self) -> RecordedRun:
        return self.runs[-1]

    def reply_with(self, behavior: Behavior) -> None:
        self.behavior = behavior

    def reply_to_offer_with(self, behavior: OfferBehavior) -> None:
        self.offer_behavior = behavior

    def client_for(self, base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(self._handle))

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/offer":
            self.offer_requests.append(RecordedOfferRequest(str(request.url), request.headers))
            return await self.offer_behavior(request)
        run = RecordedRun(str(request.url), request.headers, json.loads(request.content))
        self.runs.append(run)
        return await self.behavior(run)


@dataclass
class CowriterStack:
    agent: FakeAgentService
    issuer: FakeIssuer
    session_id: str


def attach_cowriter_service(
    client: TestClient,
    factory,
    monkeypatch,
    user_id: str,
    *,
    refresh_token: str | None = A_REFRESH_TOKEN,
) -> CowriterStack:
    """Wire a test app so ``POST /chat/turn`` runs against the fake service and realm.

    The client leaves signed in as ``user_id`` with a session that holds ``refresh_token``.
    """
    from webauth.config import installed_web_auth_config

    from songmaker_cli.auth_stores import DatabaseSessionRecordStore
    from songmaker_cli.settings import get_settings

    app = client.app
    monkeypatch.setenv("AGENT_SERVICE_URL", SERVICE_URL)
    get_settings.cache_clear()
    setattr(app.state, AVAILABILITY_ATTRIBUTE, McpEndpointAvailability())
    issuer = a_fake_issuer()
    app.state.oidc_sign_in = issuer.relying_party_for_app()
    agent = FakeAgentService()
    monkeypatch.setattr(service_turn, "service_client", agent.client_for)
    monkeypatch.setattr(service_offer, "service_client", agent.client_for)

    config = installed_web_auth_config(app)
    now = datetime.now(timezone.utc)
    with factory() as session:
        record = DatabaseSessionRecordStore(session).create(
            user_id,
            now=now,
            expires_at=now + timedelta(seconds=config.session_lifetime.idle_seconds),
            refresh_token=None if refresh_token is None else _secret(refresh_token),
        )
        session.commit()
        session_id = record.id
    for name, value in issued_cookies(session_id, config).items():
        client.cookies.set(name, value)
    apply_csrf_header(client)
    return CowriterStack(agent, issuer, session_id)


def signed_in_request(client: TestClient):
    """A request that carries the client's cookies, for tests that call an endpoint directly."""
    from starlette.requests import Request

    cookie_header = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
    return Request({
        "type": "http",
        "app": client.app,
        "headers": [(b"cookie", cookie_header.encode())],
    })


def _secret(value: str):
    from pydantic import SecretStr

    return SecretStr(value)
