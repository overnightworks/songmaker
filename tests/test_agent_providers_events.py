"""The wire contract of the co-writer stream frames the UI reads."""

from __future__ import annotations

import pytest

from agent_providers.events import (
    AssistantTextEvent,
    FinalEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from songmaker_cli.conversation_api import (
    ChatTurnFailureFrame,
    ChatTurnRouteErrorFrame,
    _sse_format,
)
from agent_providers.errors import SafeRouteReasonCode, normalize_route_failure

A_CORRELATION_ID = "job-42"

PROVIDER_EVENTS = [
    (
        AssistantTextEvent(text="Let me look at that song."),
        'data: {"type": "assistant_text", "text": "Let me look at that song."}\n\n',
    ),
    (
        ToolCallEvent(tool_use_id="call-1", name="get_song", input={"song_id": "s1"}),
        'data: {"type": "tool_call", "tool_use_id": "call-1", "name": "get_song",'
        ' "input": {"song_id": "s1"}}\n\n',
    ),
    (
        ToolResultEvent(tool_use_id="call-1", content="Ballad in D", is_error=False),
        'data: {"type": "tool_result", "tool_use_id": "call-1", "content": "Ballad in D",'
        ' "is_error": false}\n\n',
    ),
    (
        FinalEvent(text="Here is the second verse."),
        'data: {"type": "final", "text": "Here is the second verse."}\n\n',
    ),
]

ERROR_FRAMES = [
    (
        ChatTurnRouteErrorFrame(
            status=503,
            provider="grok",
            route="cli",
            reason=normalize_route_failure(SafeRouteReasonCode.CLI_BINARY_UNAVAILABLE),
        ),
        'data: {"type": "error", "status": 503, "provider": "grok", "route": "cli",'
        ' "reason": {"code": "cli_binary_unavailable", "message": "CLI is unavailable."}}\n\n',
    ),
    (
        ChatTurnFailureFrame(status=500, message="Chat request failed"),
        'data: {"type": "error", "status": 500, "message": "Chat request failed"}\n\n',
    ),
]

A_TURN = PROVIDER_EVENTS + ERROR_FRAMES


@pytest.mark.parametrize("event, payload", A_TURN, ids=lambda value: getattr(value, "type", ""))
def test_every_frame_of_a_turn_serializes_to_its_established_sse_payload(event, payload):
    assert _sse_format(event) == payload


@pytest.mark.parametrize(
    "event, payload", PROVIDER_EVENTS, ids=lambda value: getattr(value, "type", ""),
)
def test_a_correlated_event_puts_no_extra_byte_on_the_wire(event, payload):
    """The host's own handle for the turn rides along for its logs, never to a client."""
    correlated = event.model_copy(update={"correlation_id": A_CORRELATION_ID})

    assert correlated.correlation_id == A_CORRELATION_ID
    assert _sse_format(correlated) == payload


def test_a_tool_call_without_input_still_carries_an_empty_input_object():
    assert _sse_format(ToolCallEvent(tool_use_id="call-1", name="get_song")) == (
        'data: {"type": "tool_call", "tool_use_id": "call-1", "name": "get_song", "input": {}}\n\n'
    )


def test_a_tool_result_defaults_to_a_successful_result():
    assert _sse_format(ToolResultEvent(tool_use_id="call-1", content="Ballad in D")) == (
        'data: {"type": "tool_result", "tool_use_id": "call-1", "content": "Ballad in D",'
        ' "is_error": false}\n\n'
    )
