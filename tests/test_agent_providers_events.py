"""The wire contract of the provider stream events the co-writer UI reads."""

from __future__ import annotations

import pytest

from agent_providers.events import (
    AssistantTextEvent,
    ErrorEvent,
    FinalEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from songmaker_cli.conversation_api import _sse_format

A_TURN = [
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
        ErrorEvent(message="Co-Writer tool failed."),
        'data: {"type": "error", "message": "Co-Writer tool failed."}\n\n',
    ),
    (
        FinalEvent(text="Here is the second verse."),
        'data: {"type": "final", "text": "Here is the second verse."}\n\n',
    ),
]


@pytest.mark.parametrize("event, payload", A_TURN, ids=lambda value: getattr(value, "type", ""))
def test_every_event_of_a_turn_serializes_to_its_established_sse_payload(event, payload):
    assert _sse_format(event) == payload


def test_a_tool_call_without_input_still_carries_an_empty_input_object():
    assert _sse_format(ToolCallEvent(tool_use_id="call-1", name="get_song")) == (
        'data: {"type": "tool_call", "tool_use_id": "call-1", "name": "get_song", "input": {}}\n\n'
    )


def test_a_tool_result_defaults_to_a_successful_result():
    assert _sse_format(ToolResultEvent(tool_use_id="call-1", content="Ballad in D")) == (
        'data: {"type": "tool_result", "tool_use_id": "call-1", "content": "Ballad in D",'
        ' "is_error": false}\n\n'
    )
