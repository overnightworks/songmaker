"""The transport-independent co-writer tool loop.

Transports own their provider wire format.  This module owns the single
conversation rule shared by every tool-capable route: one initial turn,
at most eight tool rounds, then one final-text chance.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from songmaker_cli.claude.provider import (
    AssistantTextEvent,
    FinalEvent,
    StreamEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from songmaker_cli.constants import COWRITER_MAX_TOOL_ROUNDS

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class InitialTurn:
    """The system prompt and conversation history sent once per turn."""

    system: str
    messages: list[dict[str, str]]


@dataclass(frozen=True)
class ToolCall:
    """A provider-normalized requested tool invocation."""

    tool_use_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolCallBatch:
    """All tool calls returned by one provider response, in source order."""

    calls: tuple[ToolCall, ...]


@dataclass(frozen=True)
class ToolResult:
    """One completed invocation returned to the transport."""

    tool_use_id: str
    content: str
    is_error: bool


@dataclass(frozen=True)
class ToolResultBatch:
    """The complete result batch for a single provider response."""

    results: tuple[ToolResult, ...]


@dataclass(frozen=True)
class TextDelta:
    """A streamed assistant-text delta."""

    text: str


@dataclass(frozen=True)
class FinalText:
    """The terminal response, optionally carrying unstreamed text."""

    text: str = ""


TransportResponse = TextDelta | ToolCallBatch | FinalText
ToolExecutor = Callable[[str, dict[str, Any]], tuple[str, bool]]


class ToolTransport(Protocol):
    """Stateful provider transport for one co-writer turn."""

    def stream(
        self, message: InitialTurn | ToolResultBatch,
    ) -> AsyncIterator[TransportResponse]: ...

    def aclose(self) -> Awaitable[None]: ...


class ToolLoopError(Exception):
    """Base error for a violated transport-loop contract."""


class ToolLoopLimitError(ToolLoopError):
    """The provider requested a ninth tool round."""


class ToolLoopProtocolError(ToolLoopError):
    """The transport did not end a response with one valid terminal value."""


async def stream_tool_loop(
    *,
    provider: str,
    route: str,
    system: str,
    messages: list[dict[str, str]],
    transport: ToolTransport,
    executor: ToolExecutor,
) -> AsyncIterator[StreamEvent]:
    """Stream one turn while executing provider-normalized tool batches.

    A transport sees the initial turn first.  Every subsequent request gets
    one complete ``ToolResultBatch`` so providers with native multi-call
    responses never lose their ordering or split a round into separate turns.
    """
    next_message: InitialTurn | ToolResultBatch = InitialTurn(system, messages)
    text_chunks: list[str] = []
    round_index = 0
    try:
        while True:
            terminal: ToolCallBatch | FinalText | None = None
            async for response in _stream_transport_response(
                transport, next_message, text_chunks,
            ):
                if isinstance(response, AssistantTextEvent):
                    yield response
                else:
                    terminal = response
            if isinstance(terminal, FinalText):
                if terminal.text:
                    text_chunks.append(terminal.text)
                    yield AssistantTextEvent(text=terminal.text)
                yield FinalEvent(text="".join(text_chunks).strip())
                return
            if round_index == COWRITER_MAX_TOOL_ROUNDS:
                raise ToolLoopLimitError()
            round_index += 1
            results: list[ToolResult] = []
            async for event in _stream_tool_results(
                terminal.calls, executor, provider, route, round_index, results,
            ):
                yield event
            next_message = ToolResultBatch(tuple(results))
    finally:
        await transport.aclose()


async def _stream_transport_response(
    transport: ToolTransport,
    message: InitialTurn | ToolResultBatch,
    text_chunks: list[str],
) -> AsyncIterator[AssistantTextEvent | ToolCallBatch | FinalText]:
    terminal: ToolCallBatch | FinalText | None = None
    async for response in transport.stream(message):
        if isinstance(response, TextDelta):
            if terminal is not None:
                raise ToolLoopProtocolError()
            if response.text:
                text_chunks.append(response.text)
                yield AssistantTextEvent(text=response.text)
            continue
        if not isinstance(response, (ToolCallBatch, FinalText)) or terminal is not None:
            raise ToolLoopProtocolError()
        if isinstance(response, ToolCallBatch) and not response.calls:
            raise ToolLoopProtocolError()
        terminal = response
    if terminal is None:
        raise ToolLoopProtocolError()
    yield terminal


async def _stream_tool_results(
    calls: tuple[ToolCall, ...],
    executor: ToolExecutor,
    provider: str,
    route: str,
    round_index: int,
    results: list[ToolResult],
) -> AsyncIterator[ToolCallEvent | ToolResultEvent]:
    for call in calls:
        yield ToolCallEvent(
            tool_use_id=call.tool_use_id,
            name=call.name,
            input=call.arguments,
        )
        result, is_error = _execute_tool(executor, provider, route, round_index, call)
        yield ToolResultEvent(
            tool_use_id=call.tool_use_id,
            content=result,
            is_error=is_error,
        )
        results.append(ToolResult(call.tool_use_id, result, is_error))


def _execute_tool(
    executor: ToolExecutor,
    provider: str,
    route: str,
    round_index: int,
    call: ToolCall,
) -> tuple[str, bool]:
    started_at = time.monotonic()
    try:
        result, is_error = executor(call.name, call.arguments)
    except Exception:
        result, is_error = "Co-Writer tool failed.", True
    duration_ms = round((time.monotonic() - started_at) * 1000)
    log.info(
        "Co-writer tool provider=%s route=%s round=%s call_id=%s "
        "duration_ms=%s tool=%s is_error=%s",
        provider,
        route,
        round_index,
        call.tool_use_id,
        duration_ms,
        call.name,
        is_error,
    )
    return result, is_error
