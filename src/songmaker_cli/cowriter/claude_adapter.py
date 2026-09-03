"""Claude co-writer adapter — MCP CLI transport around songmaker tools."""

from __future__ import annotations

from collections.abc import AsyncIterator

from songmaker_cli.claude.provider import (
    StreamEvent,
    UnavailableError,
    acall_claude_with_mcp_stream,
    call_claude,
)
from songmaker_cli.constants import COWRITER_CLI_TIMEOUT_SECONDS
from songmaker_cli.cowriter.errors import ProviderUnavailableError
from songmaker_cli.settings import get_settings


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


def call_claude_once(
    *, model: str, prompt: str, timeout: int, system: str | None = None,
) -> str:
    """Synchronous, tool-free, single-turn completion.

    Used by the lyrical-coherence judge (#315), which needs one verdict, not
    the MCP-attached multi-turn co-writer chat that ``stream_claude_turn``
    gives a real song-editing session.
    """
    settings = get_settings()
    api_key = (
        settings.anthropic_api_key.get_secret_value()
        if settings.anthropic_api_key else None
    )
    try:
        response = call_claude(
            prompt,
            api_key=api_key,
            system=system,
            model=model,
            timeout_seconds=timeout,
        )
    except UnavailableError as exc:
        raise ProviderUnavailableError("claude", str(exc)) from exc
    return response.text
