"""The wire contract of the co-writer stream frames the UI reads."""

from __future__ import annotations

import pytest

from songmaker_cli.api_models import (
    AssistantTextEvent,
    ChatMessageResponse,
    ChatTurnFailureFrame,
    ChatTurnFinalFrame,
    ChatTurnProblem,
    ChatTurnProblemFrame,
    ToolCallEvent,
    ToolResultEvent,
)
from songmaker_cli.conversation_api import _sse_format

STREAM_EVENTS = [
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
]

A_MESSAGE_TIME = "2026-10-24T10:00:00+00:00"


def a_message(message_id: str, role: str, content: str) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message_id, role=role, content=content, created_at=A_MESSAGE_TIME,
    )


FINAL_FRAME = (
    ChatTurnFinalFrame(
        conversation_id="conv-1",
        user_message=a_message("m1", "user", "Hi"),
        assistant_message=a_message("m2", "assistant", "Hello"),
    ),
    'data: {"type": "final", "conversation_id": "conv-1", "user_message":'
    ' {"id": "m1", "role": "user", "content": "Hi",'
    f' "created_at": "{A_MESSAGE_TIME}"}}, "assistant_message":'
    ' {"id": "m2", "role": "assistant", "content": "Hello",'
    f' "created_at": "{A_MESSAGE_TIME}"}}}}\n\n',
)

ERROR_FRAMES = [
    (
        ChatTurnProblemFrame(status=503, problem=ChatTurnProblem.UNAVAILABLE),
        'data: {"type": "error", "status": 503, "problem": "unavailable",'
        ' "retry_after_seconds": null}\n\n',
    ),
    (
        ChatTurnProblemFrame(
            status=429, problem=ChatTurnProblem.BUSY, retry_after_seconds=30,
        ),
        'data: {"type": "error", "status": 429, "problem": "busy",'
        ' "retry_after_seconds": 30}\n\n',
    ),
    (
        ChatTurnProblemFrame(status=403, problem=ChatTurnProblem.NOT_ENABLED),
        'data: {"type": "error", "status": 403, "problem": "not_enabled",'
        ' "retry_after_seconds": null}\n\n',
    ),
    (
        ChatTurnProblemFrame(status=401, problem=ChatTurnProblem.SIGN_IN_AGAIN),
        'data: {"type": "error", "status": 401, "problem": "sign_in_again",'
        ' "retry_after_seconds": null}\n\n',
    ),
    (
        ChatTurnFailureFrame(status=500, message="Chat request failed"),
        'data: {"type": "error", "status": 500, "message": "Chat request failed"}\n\n',
    ),
]

A_TURN = [*STREAM_EVENTS, FINAL_FRAME, *ERROR_FRAMES]


@pytest.mark.parametrize("event, payload", A_TURN, ids=lambda value: getattr(value, "type", ""))
def test_every_frame_of_a_turn_serializes_to_its_established_sse_payload(event, payload):
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
