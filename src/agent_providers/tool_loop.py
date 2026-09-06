"""The transport-independent co-writer tool loop.

Transports own their provider wire format.  This module owns the single
conversation rule shared by every tool-capable route: one initial turn,
at most eight tool rounds, then one final-text chance.

The host supplies the two things this loop cannot know: the ``ToolExecutor``
that actually runs a tool, and the sentence a caller sees when that executor
fails — one owner for that text, in the host's error vocabulary.

Self-contained by design: no application import, so the package can be
released on its own (issue #825).
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from agent_providers.events import (
    AssistantTextEvent,
    FinalEvent,
    StreamEvent,
    ToolCallEvent,
    ToolResultEvent,
)

log = logging.getLogger(__name__)

COWRITER_MAX_TOOL_ROUNDS = 8


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
class ToolOutcome:
    """What a ``ToolExecutor`` returns for one requested tool invocation.

    The executor never learns which call it answers, so the loop — not the
    host — pairs this outcome with its ``tool_use_id`` into a ``ToolResult``.
    """

    content: str
    is_error: bool


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
ToolExecutor = Callable[[str, dict[str, Any]], ToolOutcome]


class ToolTransport(Protocol):
    """Stateful provider transport for one co-writer turn."""

    def stream(
        self,
        message: InitialTurn | ToolResultBatch,
    ) -> AsyncIterator[TransportResponse]: ...

    def aclose(self) -> Awaitable[None]: ...


@dataclass(frozen=True)
class _ToolRound:
    """Everything one round of tool execution needs beyond the calls themselves."""

    executor: ToolExecutor
    provider: str
    route: str
    round_index: int
    tool_failure_message: str
    correlation_id: str | None


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
    tool_failure_message: str,
    correlation_id: str | None = None,
) -> AsyncIterator[StreamEvent]:
    """Stream one turn while executing provider-normalized tool batches.

    A transport sees the initial turn first.  Every subsequent request gets
    one complete ``ToolResultBatch`` so providers with native multi-call
    responses never lose their ordering or split a round into separate turns.

    ``tool_failure_message`` is what an executor crash reports back to the
    model and the user; the host owns that sentence.  ``correlation_id``
    stamps every event this turn emits, for the host's own logs — it is
    excluded from serialization and never reaches a wire payload.
    """
    next_message: InitialTurn | ToolResultBatch = InitialTurn(system, messages)
    text_chunks: list[str] = []
    round_index = 0
    try:
        while True:
            terminal: ToolCallBatch | FinalText | None = None
            async for response in _stream_response_events(
                transport, next_message, text_chunks, correlation_id,
            ):
                if isinstance(response, AssistantTextEvent):
                    yield response
                else:
                    terminal = response
            if isinstance(terminal, FinalText):
                async for event in _final_events(terminal, text_chunks, correlation_id):
                    yield event
                return
            round_index = _next_round_index(round_index)
            results: list[ToolResult] = []
            async for event in _stream_tool_results(
                terminal.calls,
                _ToolRound(
                    executor=executor,
                    provider=provider,
                    route=route,
                    round_index=round_index,
                    tool_failure_message=tool_failure_message,
                    correlation_id=correlation_id,
                ),
                results,
            ):
                yield event
            next_message = ToolResultBatch(tuple(results))
    finally:
        await transport.aclose()


async def _stream_response_events(
    transport: ToolTransport,
    message: InitialTurn | ToolResultBatch,
    text_chunks: list[str],
    correlation_id: str | None,
) -> AsyncIterator[AssistantTextEvent | ToolCallBatch | FinalText]:
    async for response in _stream_transport_response(
        transport, message, text_chunks, correlation_id,
    ):
        yield response


async def _final_events(
    terminal: FinalText,
    text_chunks: list[str],
    correlation_id: str | None,
) -> AsyncIterator[AssistantTextEvent | FinalEvent]:
    if terminal.text:
        text_chunks.append(terminal.text)
        yield AssistantTextEvent(text=terminal.text, correlation_id=correlation_id)
    yield FinalEvent(text="".join(text_chunks).strip(), correlation_id=correlation_id)


def _next_round_index(round_index: int) -> int:
    if round_index == COWRITER_MAX_TOOL_ROUNDS:
        raise ToolLoopLimitError()
    return round_index + 1


async def _stream_transport_response(
    transport: ToolTransport,
    message: InitialTurn | ToolResultBatch,
    text_chunks: list[str],
    correlation_id: str | None,
) -> AsyncIterator[AssistantTextEvent | ToolCallBatch | FinalText]:
    terminal: ToolCallBatch | FinalText | None = None
    async for response in transport.stream(message):
        if isinstance(response, TextDelta):
            async for event in _text_delta_events(
                response, text_chunks, terminal, correlation_id,
            ):
                yield event
            continue
        _validate_terminal_response(response, terminal)
        terminal = response
    if terminal is None:
        raise ToolLoopProtocolError()
    yield terminal


async def _text_delta_events(
    response: TextDelta,
    text_chunks: list[str],
    terminal: ToolCallBatch | FinalText | None,
    correlation_id: str | None,
) -> AsyncIterator[AssistantTextEvent]:
    if terminal is not None:
        raise ToolLoopProtocolError()
    if response.text:
        text_chunks.append(response.text)
        yield AssistantTextEvent(text=response.text, correlation_id=correlation_id)


def _validate_terminal_response(
    response: TransportResponse,
    terminal: ToolCallBatch | FinalText | None,
) -> None:
    if terminal is not None or not isinstance(response, (ToolCallBatch, FinalText)):
        raise ToolLoopProtocolError()
    if isinstance(response, ToolCallBatch) and not response.calls:
        raise ToolLoopProtocolError()


async def _stream_tool_results(
    calls: tuple[ToolCall, ...],
    tool_round: _ToolRound,
    results: list[ToolResult],
) -> AsyncIterator[ToolCallEvent | ToolResultEvent]:
    for call in calls:
        yield ToolCallEvent(
            tool_use_id=call.tool_use_id,
            name=call.name,
            input=call.arguments,
            correlation_id=tool_round.correlation_id,
        )
        outcome = _execute_tool(tool_round, call)
        yield ToolResultEvent(
            tool_use_id=call.tool_use_id,
            content=outcome.content,
            is_error=outcome.is_error,
            correlation_id=tool_round.correlation_id,
        )
        results.append(ToolResult(call.tool_use_id, outcome.content, outcome.is_error))


def _execute_tool(tool_round: _ToolRound, call: ToolCall) -> ToolOutcome:
    started_at = time.monotonic()
    try:
        outcome = tool_round.executor(call.name, call.arguments)
    except Exception as exc:
        # A host executor reports a failed tool as an outcome, so anything
        # raised past it is a defect or an infrastructure failure, not an
        # answer. The turn survives it; the class is named so it is findable,
        # and the message never is — it may quote the song.
        log.error("Co-writer tool executor raised %s", type(exc).__name__)
        outcome = ToolOutcome(tool_round.tool_failure_message, True)
    duration_ms = round((time.monotonic() - started_at) * 1000)
    log.info(
        "Co-writer tool provider=%s route=%s round=%s call_id=%s "
        "correlation_id=%s duration_ms=%s tool=%s is_error=%s",
        tool_round.provider,
        tool_round.route,
        tool_round.round_index,
        call.tool_use_id,
        tool_round.correlation_id,
        duration_ms,
        call.name,
        outcome.is_error,
    )
    return outcome
