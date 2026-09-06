"""The event family a provider turn streams to its caller.

Every transport — Claude's CLI/MCP stream, the OpenAI-compatible HTTP
adapters, the tool loop — yields these types, and the host application
serialises them straight onto the wire, so their field names and defaults
are a public contract rather than an internal shape.

Self-contained by design: pydantic only, no application import, so the
package can be released on its own (issue #825).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StreamEvent(BaseModel):
    """Base class for every event a provider turn streams.

    ``correlation_id`` is the host's own handle for the turn that produced
    the event — a job id, a request id — carried so the host can log and
    group events without threading a second value beside them. It is
    excluded from serialization: the wire payload is the same with it as
    without it.
    """

    type: str
    correlation_id: str | None = Field(default=None, exclude=True)


class AssistantTextEvent(StreamEvent):
    type: Literal["assistant_text"] = "assistant_text"
    text: str


class ToolCallEvent(StreamEvent):
    type: Literal["tool_call"] = "tool_call"
    tool_use_id: str
    name: str
    input: dict = Field(default_factory=dict)


class ToolResultEvent(StreamEvent):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


class FinalEvent(StreamEvent):
    type: Literal["final"] = "final"
    text: str
