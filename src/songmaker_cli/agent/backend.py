"""One co-writer turn through the gateway backend.

``compose_agent_backend`` builds the ``GatewayBackend`` once at startup and holds it on the
app's state; ``run_cowriter_turn`` runs a turn on it. The turn yields songmaker-owned outcomes
to ``conversation_api`` and never calls a model itself: every refusal or failure is one typed
problem. The person's groups come from a fresh refresh grant at the issuer, so the API group
the gateway demands is checked against the realm's current answer, never a cached one.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from importlib.resources import files
from typing import TYPE_CHECKING, Final, assert_never

from agent_runtime_client import turn_events
from agent_runtime_client.agents import AgentDefinition, AgentFileError, TurnRequest, load_agent
from agent_runtime_client.backend import (
    GroupSource,
    TurnEvent,
    TurnPerson,
    TurnStopKind,
    TurnStopped,
)
from agent_runtime_client.backend.gateway import GatewayBackend
from agent_runtime_client.tools import Principal
from agent_runtime_client.turn import RejectionCode, TurnMessage
from webauth.config import installed_web_auth_config
from webauth.oidc_login import AccessTokenRefusal, AccessTokenRefusalReason, current_groups

from songmaker_cli.agent.tools import cowriter_hand_tools, cowriter_tool_declarations
from songmaker_cli.api_models import (
    AssistantTextEvent,
    ChatTurnProblem,
    ToolCallEvent,
    ToolResultEvent,
)
from songmaker_cli.auth_stores import DatabaseSessionTransaction
from songmaker_cli.oidc_client import normalised_oidc_issuer
from songmaker_cli.settings import Settings, get_settings

if TYPE_CHECKING:
    from fastapi import FastAPI
    from webauth.ports import AuthenticatedUser

log = logging.getLogger(__name__)

_AGENT_FILE: Final = "cowriter.md"
_NOT_ENABLED_CODES: Final = frozenset({RejectionCode.NOT_ENABLED, RejectionCode.FORBIDDEN})


@dataclass(frozen=True)
class TurnAnswer:
    """The turn finished; ``text`` is the answer it stores."""

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
    session_id: str
    user: AuthenticatedUser


class _GroupsRefusedError(Exception):
    def __init__(self, refusal: AccessTokenRefusal) -> None:
        super().__init__(refusal.reason.value)
        self.refusal = refusal


def compose_agent_backend(app: FastAPI, settings: Settings) -> None:
    """Hold the gateway backend on the app's state; an unset ``agent`` holds none."""
    agent = settings.agent
    app.state.agent_backend = None
    if agent is not None:
        tools = cowriter_hand_tools(app.state.ctx.db)
        app.state.agent_backend = GatewayBackend(agent, tools=tools)


@functools.cache
def _cowriter_agent() -> AgentDefinition:
    return load_agent(files("songmaker_cli") / "agents" / _AGENT_FILE, cowriter_tool_declarations())


async def run_cowriter_turn(
    caller: TurnCaller, messages: list[TurnMessage],
) -> AsyncIterator[TurnOutcome]:
    """Run one turn; the stream ends with exactly one ``TurnAnswer`` or ``TurnProblem``."""
    prepared = _prepared_turn(caller.app, messages)
    if isinstance(prepared, TurnProblem):
        yield prepared
    else:
        backend, request = prepared
        async for outcome in _run(backend, request, caller):
            yield outcome


def _prepared_turn(
    app: FastAPI, messages: list[TurnMessage],
) -> tuple[GatewayBackend, TurnRequest] | TurnProblem:
    backend = getattr(app.state, "agent_backend", None)
    if backend is None:
        return TurnProblem(ChatTurnProblem.UNAVAILABLE, "no agent configured")
    try:
        return backend, _cowriter_agent().request(messages)
    except AgentFileError:
        log.exception("The co-writer's agent file is refused")
        return TurnProblem(ChatTurnProblem.UNAVAILABLE, "agent file refused")


async def _run(
    backend: GatewayBackend, request: TurnRequest, caller: TurnCaller,
) -> AsyncIterator[TurnOutcome]:
    # Closing this generator must end the backend's turn at once, so its cleanup runs now.
    async with aclosing(backend.run(request, _person_of(caller))) as events:
        try:
            async for event in events:
                yield _outcome_of(event)
        except TurnStopped as stopped:
            yield _problem_of_stop(stopped)
        except _GroupsRefusedError as refused:
            yield _problem_of_refusal(refused.refusal)


def _person_of(caller: TurnCaller) -> TurnPerson:
    issuer = normalised_oidc_issuer(get_settings().oidc_issuer) or ""
    principal = Principal(iss=issuer, sub=caller.user.id)
    return TurnPerson(principal, caller.user.role, _groups_of(caller))


def _groups_of(caller: TurnCaller) -> GroupSource:
    async def groups() -> frozenset[str]:
        app = caller.app
        found = await asyncio.to_thread(
            current_groups,
            app.state.oidc_sign_in.relying_party,
            caller.session_id,
            session_transaction=DatabaseSessionTransaction(app.state.ctx.db),
            config=installed_web_auth_config(app),
        )
        if isinstance(found, AccessTokenRefusal):
            raise _GroupsRefusedError(found)
        return frozenset(found)

    return groups


def _outcome_of(event: TurnEvent) -> TurnOutcome:
    if isinstance(event, turn_events.AssistantTextEvent):
        return AssistantTextEvent(text=event.text)
    if isinstance(event, turn_events.ToolCallEvent):
        return ToolCallEvent(tool_use_id=event.tool_use_id, name=event.name, input=event.input)
    if isinstance(event, turn_events.ToolResultEvent):
        return ToolResultEvent(
            tool_use_id=event.tool_use_id, content=event.content, is_error=event.is_error,
        )
    if isinstance(event, turn_events.FinalEvent):
        return TurnAnswer(event.text)
    assert_never(event)


def _problem_of_stop(stopped: TurnStopped) -> TurnProblem:
    detail = f"{stopped} {stopped.detail}" if stopped.detail else str(stopped)
    if stopped.kind is TurnStopKind.REFUSED and stopped.code in _NOT_ENABLED_CODES:
        return TurnProblem(ChatTurnProblem.NOT_ENABLED, detail)
    if stopped.kind is TurnStopKind.REFUSED and stopped.code is RejectionCode.BUSY:
        return TurnProblem(ChatTurnProblem.BUSY, detail, stopped.retry_after_s)
    return TurnProblem(ChatTurnProblem.UNAVAILABLE, detail)


def _problem_of_refusal(refusal: AccessTokenRefusal) -> TurnProblem:
    if refusal.reason is AccessTokenRefusalReason.ISSUER_UNAVAILABLE:
        return TurnProblem(ChatTurnProblem.UNAVAILABLE, "issuer unavailable")
    return TurnProblem(ChatTurnProblem.SIGN_IN_AGAIN, refusal.reason.value)
