"""Claude co-writer adapter — MCP CLI transport around songmaker tools."""

from __future__ import annotations

from collections.abc import AsyncIterator

from songmaker_cli.claude.provider import (
    StreamEvent,
    UnavailableError,
    acall_claude_with_mcp_stream,
)
from songmaker_cli.constants import COWRITER_CLI_TIMEOUT_SECONDS
from songmaker_cli.cowriter.errors import ProviderUnavailableError


async def stream_claude_turn(
    *,
    user_id: str,
    system: str,
    model: str,
    messages: list[dict[str, str]],
) -> AsyncIterator[StreamEvent]:
    try:
        async for event in acall_claude_with_mcp_stream(
            prompt="",
            user_id=user_id,
            system=system,
            model=model,
            messages=messages,
            timeout_seconds=COWRITER_CLI_TIMEOUT_SECONDS,
        ):
            yield event
    except UnavailableError as exc:
        raise ProviderUnavailableError("claude", str(exc)) from exc
