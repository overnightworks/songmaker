"""The co-writer's tools as the gateway backend serves them.

A handler acts for the person the turn is for and nobody else: it takes the user only from the
turn's principal, never from the model's arguments, and the tools' schemas carry no user field.
"""

from __future__ import annotations

import asyncio
from typing import Final

from agent_runtime_client.tools import (
    HandTool,
    JsonObject,
    Principal,
    ToolDeclaration,
    ToolEffect,
    ToolOutcome,
)
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.cowriter.tools import COWRITER_TOOLS, execute_cowriter_tool
from songmaker_cli.mcp_server.auth import MCPAuthError, load_user

_REFUSED: Final = ToolOutcome("The tool call was refused.", is_error=True)


def cowriter_tool_declarations() -> list[ToolDeclaration]:
    """The co-writer's tools as the agent file selects them."""
    return [
        ToolDeclaration(
            name=tool.name,
            description=tool.description,
            parameters=tool.parameters,
            effect=ToolEffect.SIDE_EFFECTING if tool.write else ToolEffect.READ_ONLY,
        )
        for tool in COWRITER_TOOLS
    ]


def cowriter_hand_tools(session_factory: sessionmaker[Session]) -> list[HandTool]:
    return [
        HandTool(declaration, _handler_for(declaration.name, session_factory))
        for declaration in cowriter_tool_declarations()
    ]


def _handler_for(name: str, session_factory: sessionmaker[Session]):
    async def handle(principal: Principal, arguments: JsonObject) -> ToolOutcome:
        return await asyncio.to_thread(_execute, session_factory, principal.sub, name, arguments)

    return handle


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
