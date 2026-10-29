"""The co-writer's tools at ``/mcp`` for the agent service.

``compose_mcp_endpoint`` is the one owner of whether the endpoint is available: it reads the
capability verification key and the origin, and returns the ASGI app to serve together with
the verdict. A co-writer problem refuses the call, never server startup, so a missing or
malformed key leaves the web up and ``/mcp`` answering 503 with an empty body.

``/mcp`` is served outside songmaker's middleware; ``McpServer`` runs its own checks (Host,
Origin, Bearer capability, path, method, body size) and each handler accepts a call only for
the person whose running turn registered the capability's run (``service_runs``).
"""

from __future__ import annotations

import asyncio
import logging
import stat
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from typing import Final

from agent_runtime_client.capability import MCP_ENDPOINT_PATH, CapabilityClaims
from agent_runtime_client.mcp_server import (
    CapabilityVerificationKey,
    McpServer,
    McpTool,
    UnsoundVerificationKey,
)
from agent_runtime_client.mcp_wire import ToolOutcome
from agent_runtime_client.tools import ToolDeclaration, ToolEffect
from agent_runtime_client.wire import JsonObject
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.cowriter import service_runs
from songmaker_cli.cowriter.service_runs import RunPerson
from songmaker_cli.cowriter.tools import COWRITER_TOOLS, execute_cowriter_tool
from songmaker_cli.mcp_server.auth import MCPAuthError, load_user
from songmaker_cli.oidc_client import normalised_oidc_issuer
from songmaker_cli.settings import Settings

log = logging.getLogger(__name__)

CAPABILITY_APP: Final = "songmaker"
CAPABILITY_AGENT: Final = "cowriter"
_REFUSED: Final = ToolOutcome("The tool call was refused.", is_error=True)
_KEY_SETTING: Final = "agent_service_capability_key_file"
_ORIGIN_SETTING: Final = "agent_service_mcp_origin"
_TOOL_CATALOG: Final = "the co-writer tool catalog"
AVAILABILITY_ATTRIBUTE: Final = "cowriter_mcp_availability"


class McpKeyProblem(StrEnum):
    MISSING = "missing"
    NOT_A_FILE = "not a file"
    UNREADABLE = "unreadable"
    UNSOUND_KEY = "unsound key"
    ORIGIN_MISSING = "origin missing"
    ORIGIN_INVALID = "origin invalid"
    TOOLS_INVALID = "tools invalid"
    NOT_COMPOSED = "not composed"


@dataclass(frozen=True)
class McpEndpointAvailability:
    """Ready when ``problem`` is ``None``; ``reason`` is text safe to log, never key bytes."""

    problem: McpKeyProblem | None = None
    reason: str = ""


def cowriter_mcp_availability(app) -> McpEndpointAvailability:
    """The verdict ``run_server`` published; an app that never composed the endpoint has none."""
    published = getattr(app.state, AVAILABILITY_ATTRIBUTE, None)
    return published or McpEndpointAvailability(McpKeyProblem.NOT_COMPOSED)


def cowriter_tool_declarations() -> list[ToolDeclaration]:
    """The co-writer's tools as the endpoint serves them and the agent file selects them."""
    return [
        ToolDeclaration(
            name=tool.name,
            description=tool.description,
            parameters=tool.parameters,
            effect=ToolEffect.SIDE_EFFECTING if tool.write else ToolEffect.READ_ONLY,
        )
        for tool in COWRITER_TOOLS
    ]


def compose_mcp_endpoint(app, settings: Settings):
    """The app to serve and whether ``/mcp`` is available on it."""
    availability, server = _server_or_problem(app, settings)
    if server is None:
        _log_unavailable(availability)
        return _refusing_in_front_of(app), availability
    return server.in_front_of(app), availability


def _server_or_problem(
    app, settings: Settings,
) -> tuple[McpEndpointAvailability, McpServer | None]:
    origin = settings.agent_service_mcp_origin
    if not origin:
        return McpEndpointAvailability(McpKeyProblem.ORIGIN_MISSING), None
    key = _verification_key(settings)
    if isinstance(key, McpEndpointAvailability):
        return key, None
    try:
        McpServer(origin, key, [])  # the server validates the origin first; no tools to blame
    except ValidationError:
        return McpEndpointAvailability(McpKeyProblem.ORIGIN_INVALID), None
    try:
        return McpEndpointAvailability(), McpServer(origin, key, _tools_for(app, settings))
    except ValueError as invalid:  # duplicate names raise ValueError; ValidationError subclasses it
        return McpEndpointAvailability(McpKeyProblem.TOOLS_INVALID, type(invalid).__name__), None


def _verification_key(settings: Settings) -> CapabilityVerificationKey | McpEndpointAvailability:
    path = settings.agent_service_capability_key_file
    if path is None:
        return McpEndpointAvailability(McpKeyProblem.MISSING)
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return McpEndpointAvailability(McpKeyProblem.NOT_A_FILE)
        pem = path.read_bytes()
    except FileNotFoundError:
        return McpEndpointAvailability(McpKeyProblem.MISSING)
    except OSError:
        return McpEndpointAvailability(McpKeyProblem.UNREADABLE)
    try:
        return CapabilityVerificationKey.from_pem(pem)
    except UnsoundVerificationKey as unsound:
        return McpEndpointAvailability(McpKeyProblem.UNSOUND_KEY, str(unsound))


def _log_unavailable(availability: McpEndpointAvailability) -> None:
    if availability.problem in (McpKeyProblem.ORIGIN_MISSING, McpKeyProblem.ORIGIN_INVALID):
        setting = _ORIGIN_SETTING
    elif availability.problem is McpKeyProblem.TOOLS_INVALID:
        setting = _TOOL_CATALOG
    else:
        setting = _KEY_SETTING
    log.warning(
        "Co-writer MCP endpoint unavailable, /mcp answers 503: %s %s %s",
        setting,
        availability.problem.value,
        availability.reason,
    )


def _refusing_in_front_of(app):
    async def front(scope, receive, send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (
            path == MCP_ENDPOINT_PATH or path.startswith(f"{MCP_ENDPOINT_PATH}/")
        ):
            await app(scope, receive, send)
            return
        await send({
            "type": "http.response.start",
            "status": int(HTTPStatus.SERVICE_UNAVAILABLE),
            "headers": [(b"content-length", b"0")],
        })
        await send({"type": "http.response.body", "body": b""})

    return front


def _tools_for(app, settings: Settings) -> list[McpTool]:
    issuer = normalised_oidc_issuer(settings.oidc_issuer)
    return [
        McpTool(declaration, _handler_for(declaration.name, app, issuer))
        for declaration in cowriter_tool_declarations()
    ]


def _handler_for(name: str, app, issuer: str | None):
    async def handle(claims: CapabilityClaims, arguments: JsonObject) -> ToolOutcome:
        if not _is_for_the_running_turn(claims, issuer):
            return _REFUSED
        return await asyncio.to_thread(
            _execute, app.state.ctx.db, claims.principal.sub, name, arguments,
        )

    return handle


def _is_for_the_running_turn(claims: CapabilityClaims, issuer: str | None) -> bool:
    if claims.app != CAPABILITY_APP or claims.agent != CAPABILITY_AGENT:
        return False
    if claims.principal.iss != issuer:
        return False
    return service_runs.holder(claims.sub) == RunPerson(
        claims.principal.iss, claims.principal.sub,
    )


def _execute(
    session_factory: sessionmaker[Session], user_id: str, name: str, arguments: JsonObject,
) -> ToolOutcome:
    with session_factory() as session:
        try:
            user = load_user(session, user_id)
        except MCPAuthError:
            return _REFUSED
        outcome = execute_cowriter_tool(session, user, name, arguments)
    return ToolOutcome(outcome.content, outcome.is_error)
