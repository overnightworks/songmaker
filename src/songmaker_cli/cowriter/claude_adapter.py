"""Claude co-writer adapters for the CLI/MCP and native API tool transports."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.orm import Session

from songmaker_cli.claude.provider import (
    AssistantTextEvent,
    CliBinaryUnavailableError,
    CliToolSurfaceError,
    FinalEvent,
    StreamEvent,
    ToolCallEvent,
    ToolResultEvent,
    UnavailableError,
    acall_claude_with_mcp_stream,
    call_claude,
)
from songmaker_cli.constants import (
    COWRITER_CLAUDE_API_MAX_TOKENS,
    COWRITER_CLI_TIMEOUT_SECONDS,
    COWRITER_MAX_TOOL_ROUNDS,
)
from songmaker_cli.cowriter.errors import (
    ProviderUnavailableError,
    SafeRouteReasonCode,
    normalize_route_failure,
)
from songmaker_cli.middleware import AuthenticatedUser
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)


async def stream_claude_turn(
    *,
    user_id: str,
    system: str,
    model: str,
    messages: list[dict[str, str]],
) -> AsyncIterator[StreamEvent]:
    stream = acall_claude_with_mcp_stream(
        prompt="",
        user_id=user_id,
        system=system,
        model=model,
        messages=messages,
        timeout_seconds=COWRITER_CLI_TIMEOUT_SECONDS,
    )
    try:
        async for event in stream:
            yield event
    except UnavailableError as exc:
        raise ProviderUnavailableError(
            "claude",
            "cli",
            normalize_route_failure(_claude_cli_failure_reason(exc)),
        ) from exc
    finally:
        await stream.aclose()


async def stream_claude_api_turn(
    *,
    api_key: str,
    system: str,
    model: str,
    messages: list[dict[str, str]],
    session: Session,
    user: AuthenticatedUser,
) -> AsyncIterator[StreamEvent]:
    """Stream one Claude API co-writer turn through the shared tool catalog."""
    from songmaker_cli.cowriter.tools import anthropic_tool_schemas, execute_cowriter_tool

    anthropic_messages: list[dict[str, object]] = [dict(message) for message in messages]
    text_chunks: list[str] = []
    anthropic = None
    try:
        anthropic = _require_anthropic_for_cowriter()
        async with anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=COWRITER_CLI_TIMEOUT_SECONDS,
            max_retries=0,
        ) as client:
            for round_index in range(COWRITER_MAX_TOOL_ROUNDS + 1):
                async with client.messages.stream(
                    model=model,
                    max_tokens=COWRITER_CLAUDE_API_MAX_TOKENS,
                    system=system,
                    messages=anthropic_messages,
                    tools=anthropic_tool_schemas(),
                ) as stream:
                    async for text in stream.text_stream:
                        if not isinstance(text, str):
                            raise _protocol_error(SafeRouteReasonCode.API_PROTOCOL_ERROR)
                        text_chunks.append(text)
                        yield AssistantTextEvent(text=text)
                    assistant_message = await stream.get_final_message()
                content = _assistant_content(assistant_message)
                tool_uses = _tool_uses(content)
                if tool_uses and round_index == COWRITER_MAX_TOOL_ROUNDS:
                    raise _protocol_error(SafeRouteReasonCode.TOOL_LIMIT_EXCEEDED)
                if not tool_uses:
                    yield FinalEvent(text="".join(text_chunks).strip())
                    return
                anthropic_messages.append({"role": "assistant", "content": content})
                tool_results: list[dict[str, object]] = []
                for tool_use_id, name, arguments in tool_uses:
                    yield ToolCallEvent(tool_use_id=tool_use_id, name=name, input=arguments)
                    try:
                        result, is_error = execute_cowriter_tool(session, user, name, arguments)
                    except Exception as exc:
                        log.warning("Claude API co-writer tool failed class=%s", type(exc).__name__)
                        raise _protocol_error(SafeRouteReasonCode.TOOL_EXECUTION_FAILED) from exc
                    yield ToolResultEvent(
                        tool_use_id=tool_use_id,
                        content=result,
                        is_error=is_error,
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": result,
                        "is_error": is_error,
                    })
                anthropic_messages.append({"role": "user", "content": tool_results})
    except ProviderUnavailableError:
        raise
    except Exception as exc:
        log.warning("Claude API co-writer failed class=%s", type(exc).__name__)
        raise _sdk_failure(anthropic, exc) from exc
    raise AssertionError("unreachable")


def _require_anthropic_for_cowriter() -> object:
    try:
        import anthropic
    except ImportError as exc:
        raise _protocol_error(SafeRouteReasonCode.API_HTTP_ERROR) from exc
    return anthropic


def _is_anthropic_api_error(anthropic: object | None, error: Exception) -> bool:
    api_error = getattr(anthropic, "APIError", None)
    return isinstance(api_error, type) and isinstance(error, api_error)


def _sdk_failure(anthropic: object | None, error: Exception) -> ProviderUnavailableError:
    code = (
        SafeRouteReasonCode.API_HTTP_ERROR
        if _is_anthropic_api_error(anthropic, error)
        else SafeRouteReasonCode.API_PROTOCOL_ERROR
    )
    return _protocol_error(code)


def _assistant_content(assistant_message: object) -> list[object]:
    content = getattr(assistant_message, "content", None)
    if not isinstance(content, list):
        raise _protocol_error(SafeRouteReasonCode.API_PROTOCOL_ERROR)
    return content


def _tool_uses(content: list[object]) -> list[tuple[str, str, dict[str, Any]]]:
    tool_uses: list[tuple[str, str, dict[str, Any]]] = []
    for block in content:
        if getattr(block, "type", None) != "tool_use":
            continue
        tool_use_id = getattr(block, "id", None)
        name = getattr(block, "name", None)
        arguments = getattr(block, "input", None)
        if (
            not isinstance(tool_use_id, str)
            or not tool_use_id
            or not isinstance(name, str)
            or not name
            or not isinstance(arguments, dict)
        ):
            raise _protocol_error(SafeRouteReasonCode.TOOL_PROTOCOL_ERROR)
        tool_uses.append((tool_use_id, name, arguments))
    return tool_uses


def _protocol_error(code: SafeRouteReasonCode) -> ProviderUnavailableError:
    return ProviderUnavailableError("claude", "api", normalize_route_failure(code))


def _claude_cli_failure_reason(error: UnavailableError) -> SafeRouteReasonCode:
    """Map typed Claude CLI failures without exposing their diagnostics."""
    if isinstance(error, CliBinaryUnavailableError):
        return SafeRouteReasonCode.CLI_BINARY_UNAVAILABLE
    if isinstance(error, CliToolSurfaceError):
        return SafeRouteReasonCode.TOOL_EXECUTION_FAILED
    return SafeRouteReasonCode.CLI_PROTOCOL_ERROR


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
    except UnavailableError:
        # The API-only judge owns its established failure detail (for example
        # ``judge_timeout``); the co-writer route never calls this adapter.
        raise
    return response.text
