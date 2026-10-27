"""One co-writer turn as a run at the agent service.

The turn checks the endpoint's verdict, turns the session's refresh token into a fresh user
access token and takes songmaker's workload token, then starts a run of ``agents/cowriter.md``
and reads its event stream to the end. It yields songmaker-owned outcomes to ``conversation_api``
and never runs a model itself: every refusal or failure is one typed problem.

The run is registered with ``service_runs`` when ``run_started`` arrives and released when the
turn's stream ends, whatever ends it, so ``/mcp`` accepts the run's tool calls exactly while this
person's turn runs (Q8). None of the three tokens is logged, yielded or stored.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from importlib.resources import files
from typing import TYPE_CHECKING, Final

import httpx
from agent_runtime_client.agents import AgentDefinition, AgentFileError, load_agent
from agent_runtime_client.run_stream import StreamViolation
from agent_runtime_client.sse import RunStreamDecoder
from agent_runtime_client.wire import (
    AssistantText,
    Cancelled,
    Failed,
    Heartbeat,
    RejectionCode,
    RunEvent,
    RunRejection,
    RunStarted,
    Succeeded,
    ToolCall,
    ToolResult,
    TurnMessage,
)
from pydantic import SecretStr, ValidationError
from webauth.config import installed_web_auth_config
from webauth.oidc import OidcRefusal
from webauth.oidc_login import AccessTokenRefusal, AccessTokenRefusalReason, fresh_access_token

from songmaker_cli.api_models import (
    AssistantTextEvent,
    ChatTurnProblem,
    ToolCallEvent,
    ToolResultEvent,
)
from songmaker_cli.auth_stores import DatabaseSessionTransaction
from songmaker_cli.cowriter import service_runs
from songmaker_cli.cowriter.service_runs import RunPerson
from songmaker_cli.oidc_client import normalised_oidc_issuer
from songmaker_cli.settings import get_settings

if TYPE_CHECKING:
    from fastapi import FastAPI
    from webauth.ports import AuthenticatedUser

log = logging.getLogger(__name__)

RUNS_PATH: Final = "/runs"
WORKLOAD_TOKEN_HEADER: Final = "Agent-Workload-Token"  # noqa: S105
_AGENT_FILE: Final = "cowriter.md"
_RETRY_AFTER_HEADER: Final = "Retry-After"
# A run's heartbeat comes at most every 300 seconds; the read timeout outlasts one.
_READ_TIMEOUT_SECONDS: Final = 330.0
_CONNECT_TIMEOUT_SECONDS: Final = 10.0
_OTHER_TIMEOUT_SECONDS: Final = 30.0


@dataclass(frozen=True)
class TurnAnswer:
    """The run succeeded; ``text`` is the answer the turn stores."""

    text: str


@dataclass(frozen=True)
class TurnProblem:
    """The turn did not run to an answer. ``detail`` is a closed name, safe to log and store."""

    problem: ChatTurnProblem
    detail: str
    retry_after_seconds: int | None = None


TurnOutcome = AssistantTextEvent | ToolCallEvent | ToolResultEvent | TurnAnswer | TurnProblem


@dataclass(frozen=True)
class TurnCaller:
    """Whose turn it is and what the turn needs from the web app: its realm and its database."""

    app: FastAPI
    session_id: str | None
    user: AuthenticatedUser


@dataclass(frozen=True)
class _RunTokens:
    user: SecretStr
    workload: SecretStr


def service_client(base_url: str) -> httpx.AsyncClient:
    """The one HTTP client of the run: no proxy from the environment, no redirects."""
    return httpx.AsyncClient(
        base_url=base_url,
        trust_env=False,
        timeout=httpx.Timeout(
            _OTHER_TIMEOUT_SECONDS, connect=_CONNECT_TIMEOUT_SECONDS, read=_READ_TIMEOUT_SECONDS,
        ),
    )


@functools.cache
def _cowriter_agent() -> AgentDefinition:
    # Imported here: the endpoint's tool catalog needs the optional `mcp` library, which the
    # modules the web app imports at startup must not need.
    from songmaker_cli.cowriter.mcp_endpoint import cowriter_tool_declarations

    return load_agent(files("songmaker_cli") / "agents" / _AGENT_FILE, cowriter_tool_declarations())


def cowriter_model() -> str:
    """The model the person sees: the agent file's wire id without its provider prefix."""
    return _cowriter_agent().model.rpartition("/")[2]


async def run_cowriter_turn(
    caller: TurnCaller, messages: list[TurnMessage],
) -> AsyncIterator[TurnOutcome]:
    """Run one turn; the stream ends with exactly one ``TurnAnswer`` or ``TurnProblem``."""
    unusable = _problem_before_the_run(caller.app)
    if isinstance(unusable, TurnProblem):
        yield unusable
        return
    agent, service_url = unusable
    tokens = await asyncio.to_thread(_fetch_tokens, caller.app, caller.session_id)
    if isinstance(tokens, TurnProblem):
        yield tokens
        return
    person = RunPerson(normalised_oidc_issuer(get_settings().oidc_issuer) or "", caller.user.id)
    # Closing this generator must end the run's stream at once, so its release runs now.
    async with aclosing(_stream_run(service_url, agent.request(messages), tokens, person)) as run:
        async for outcome in run:
            yield outcome


def _problem_before_the_run(app: FastAPI) -> TurnProblem | tuple[AgentDefinition, str]:
    from songmaker_cli.cowriter.mcp_endpoint import cowriter_mcp_availability

    availability = cowriter_mcp_availability(app)
    if availability.problem is not None:
        return TurnProblem(ChatTurnProblem.UNAVAILABLE, f"mcp {availability.problem.value}")
    service_url = get_settings().agent_service_url
    if not service_url:
        return TurnProblem(ChatTurnProblem.UNAVAILABLE, "no agent service url")
    try:
        return _cowriter_agent(), service_url
    except AgentFileError:
        log.exception("The co-writer's agent file is refused")
        return TurnProblem(ChatTurnProblem.UNAVAILABLE, "agent file refused")


def _fetch_tokens(app: FastAPI, session_id: str | None) -> _RunTokens | TurnProblem:
    """The person's fresh access token, then songmaker's workload token; never both unchecked."""
    if session_id is None:
        return TurnProblem(ChatTurnProblem.SIGN_IN_AGAIN, "no session")
    relying_party = app.state.oidc_sign_in.relying_party
    user = fresh_access_token(
        relying_party,
        session_id,
        session_transaction=DatabaseSessionTransaction(app.state.ctx.db),
        config=installed_web_auth_config(app),
    )
    if isinstance(user, AccessTokenRefusal):
        return _problem_of_refusal(user)
    workload = relying_party.workload_access_token()
    if isinstance(workload, OidcRefusal):
        return TurnProblem(ChatTurnProblem.UNAVAILABLE, "workload token refused")
    return _RunTokens(user, workload)


def _problem_of_refusal(refusal: AccessTokenRefusal) -> TurnProblem:
    if refusal.reason is AccessTokenRefusalReason.ISSUER_UNAVAILABLE:
        return TurnProblem(ChatTurnProblem.UNAVAILABLE, "issuer unavailable")
    return TurnProblem(ChatTurnProblem.SIGN_IN_AGAIN, refusal.reason.value)


async def _stream_run(
    service_url: str, request, tokens: _RunTokens, person: RunPerson,
) -> AsyncIterator[TurnOutcome]:
    run_id: str | None = None
    decoder = RunStreamDecoder()
    try:
        async with service_client(service_url) as client, client.stream(
            "POST",
            RUNS_PATH,
            content=request.model_dump_json(),
            headers={
                "Authorization": f"Bearer {tokens.user.get_secret_value()}",
                WORKLOAD_TOKEN_HEADER: tokens.workload.get_secret_value(),
                "Content-Type": "application/json",
            },
        ) as response:
            if response.status_code != httpx.codes.OK:
                yield await _problem_of_refused_start(response)
                return
            async with aclosing(_decoded_events(response, decoder)) as events:
                async for decoded in events:
                    if isinstance(decoded, RunStarted):
                        service_runs.register(str(decoded.run_id), person)
                        run_id = str(decoded.run_id)
                    outcome = _outcome_of(decoded)
                    if outcome is not None:
                        yield outcome
                    if isinstance(outcome, (TurnAnswer, TurnProblem)):
                        return
    except service_runs.RunAlreadyRegisteredError:
        yield TurnProblem(ChatTurnProblem.UNAVAILABLE, "run already registered")
    except httpx.HTTPError as unreachable:
        yield TurnProblem(ChatTurnProblem.UNAVAILABLE, type(unreachable).__name__)
    finally:
        if run_id is not None:
            service_runs.release(run_id)


async def _decoded_events(
    response: httpx.Response, decoder: RunStreamDecoder,
) -> AsyncIterator[RunEvent | StreamViolation]:
    async for chunk in response.aiter_bytes():
        for decoded in decoder.feed(chunk):
            yield decoded
    for violation in decoder.close():
        yield violation


def _outcome_of(decoded: RunEvent | StreamViolation) -> TurnOutcome | None:
    match decoded:
        case StreamViolation():
            return _problem_of_violation(decoded)
        case AssistantText():
            return AssistantTextEvent(text=decoded.text)
        case ToolCall():
            return ToolCallEvent(
                tool_use_id=decoded.tool_use_id, name=decoded.name, input=decoded.input,
            )
        case ToolResult():
            return ToolResultEvent(
                tool_use_id=decoded.tool_use_id, content=decoded.content,
                is_error=decoded.is_error,
            )
        case Succeeded():
            return TurnAnswer(decoded.text)
        case Failed():
            return TurnProblem(ChatTurnProblem.UNAVAILABLE, decoded.code.value)
        case Cancelled():
            return TurnProblem(ChatTurnProblem.UNAVAILABLE, "cancelled")
        case RunStarted() | Heartbeat():
            return None


def _problem_of_violation(violation: StreamViolation) -> TurnProblem:
    return TurnProblem(ChatTurnProblem.UNAVAILABLE, violation.kind.value)


async def _problem_of_refused_start(response: httpx.Response) -> TurnProblem:
    body = await response.aread()
    try:
        code = RunRejection.model_validate_json(body).code
    except ValidationError:
        return TurnProblem(ChatTurnProblem.UNAVAILABLE, f"http {response.status_code}")
    if response.status_code == httpx.codes.FORBIDDEN and code in (
        RejectionCode.NOT_ENABLED, RejectionCode.FORBIDDEN,
    ):
        return TurnProblem(ChatTurnProblem.NOT_ENABLED, code.value)
    if response.status_code == httpx.codes.TOO_MANY_REQUESTS and code is RejectionCode.BUSY:
        wait = _wait_seconds(response.headers.get(_RETRY_AFTER_HEADER))
        return TurnProblem(ChatTurnProblem.BUSY, code.value, wait)
    return TurnProblem(ChatTurnProblem.UNAVAILABLE, code.value)


def _wait_seconds(retry_after: str | None) -> int | None:
    if retry_after is None or not retry_after.isascii() or not retry_after.isdigit():
        return None
    return int(retry_after)
