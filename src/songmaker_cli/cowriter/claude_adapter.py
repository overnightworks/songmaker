"""Claude co-writer adapters for the CLI/MCP and native API tool transports."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.orm import Session

from songmaker_cli.claude.provider import (
    CliBinaryUnavailableError,
    CliToolSurfaceError,
    StreamEvent,
    UnavailableError,
    acall_claude_with_mcp_stream,
    call_claude,
)
from songmaker_cli.constants import (
    COWRITER_CLAUDE_API_MAX_TOKENS,
    COWRITER_CLI_TIMEOUT_SECONDS,
)
from songmaker_cli.cowriter.errors import (
    ProviderUnavailableError,
    SafeRouteReasonCode,
    normalize_route_failure,
)
from songmaker_cli.cowriter.tool_loop import (
    FinalText,
    InitialTurn,
    TextDelta,
    ToolCall,
    ToolCallBatch,
    ToolLoopLimitError,
    ToolLoopProtocolError,
    ToolResultBatch,
    TransportResponse,
    stream_tool_loop,
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

    anthropic = None
    try:
        anthropic = _require_anthropic_for_cowriter()
        async with anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=COWRITER_CLI_TIMEOUT_SECONDS,
            max_retries=0,
        ) as client:
            transport = _ClaudeApiTransport(
                client=client,
                model=model,
                tool_schemas=anthropic_tool_schemas(),
            )
            async for event in stream_tool_loop(
                provider="claude",
                route="api",
                system=system,
                messages=messages,
                transport=transport,
                executor=lambda name, arguments: execute_cowriter_tool(
                    session, user, name, arguments,
                ),
            ):
                yield event
    except ToolLoopLimitError as exc:
        raise _protocol_error(SafeRouteReasonCode.TOOL_LIMIT_EXCEEDED) from exc
    except ToolLoopProtocolError as exc:
        raise _protocol_error(SafeRouteReasonCode.API_PROTOCOL_ERROR) from exc
    except ProviderUnavailableError:
        raise
    except Exception as exc:
        log.warning("Claude API co-writer failed class=%s", type(exc).__name__)
        raise _sdk_failure(anthropic, exc) from exc


class _ClaudeApiTransport:
    """Claude Messages API wire format behind the shared loop contract."""

    def __init__(self, *, client: object, model: str, tool_schemas: list[dict[str, Any]]) -> None:
        self._client = client
        self._model = model
        self._tool_schemas = tool_schemas
        self._messages: list[dict[str, object]] | None = None
        self._assistant_content: list[object] | None = None

    async def aclose(self) -> None:
        """The enclosing SDK client context owns connection cleanup."""

    async def stream(
        self, message: InitialTurn | ToolResultBatch,
    ) -> AsyncIterator[TransportResponse]:
        self._append_message(message)
        messages_api = getattr(self._client, "messages", None)
        if messages_api is None:
            raise _protocol_error(SafeRouteReasonCode.API_PROTOCOL_ERROR)
        async with messages_api.stream(
            model=self._model,
            max_tokens=COWRITER_CLAUDE_API_MAX_TOKENS,
            system=self._system,
            messages=self._messages,
            tools=self._tool_schemas,
        ) as stream:
            async for text in stream.text_stream:
                if not isinstance(text, str):
                    raise _protocol_error(SafeRouteReasonCode.API_PROTOCOL_ERROR)
                if text:
                    yield TextDelta(text)
            assistant_message = await stream.get_final_message()
        content = _assistant_content(assistant_message)
        tool_uses = _tool_uses(content)
        if not tool_uses:
            yield FinalText()
            return
        self._assistant_content = content
        yield ToolCallBatch(tuple(
            ToolCall(tool_use_id, name, arguments)
            for tool_use_id, name, arguments in tool_uses
        ))

    def _append_message(self, message: InitialTurn | ToolResultBatch) -> None:
        if isinstance(message, InitialTurn):
            if self._messages is not None:
                raise ToolLoopProtocolError()
            self._system = message.system
            self._messages = [dict(item) for item in message.messages]
            return
        if self._messages is None or self._assistant_content is None:
            raise ToolLoopProtocolError()
        self._messages.append({"role": "assistant", "content": self._assistant_content})
        self._messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": result.tool_use_id,
                "content": result.content,
                "is_error": result.is_error,
            } for result in message.results],
        })
        self._assistant_content = None


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
    response = call_claude(
        prompt,
        api_key=api_key,
        system=system,
        model=model,
        timeout_seconds=timeout,
    )
    return response.text
