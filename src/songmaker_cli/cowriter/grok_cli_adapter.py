"""Grok subscription CLI transport for one tool-free co-writer turn."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from collections.abc import AsyncIterator
from typing import Final

from songmaker_cli.agent_cli import CliLineChannel, CliRunOutcome, run_cli_bounded
from songmaker_cli.claude.provider import (
    AssistantTextEvent,
    FinalEvent,
    StreamEvent,
    _flatten_messages,
    _stdin_prompt,
)
from songmaker_cli.constants import (
    COWRITER_CLI_TIMEOUT_SECONDS,
    COWRITER_GROK_CLI_LINE_CHANNEL_CAPACITY,
    GROK_CLI_BINARY,
    GROK_CLI_PROMPT_FILE_PLACEHOLDER,
    GROK_CLI_STREAMING_OUTPUT_FORMAT,
)
from songmaker_cli.cowriter.errors import ProviderUnavailableError

_AUTH_FAILURE_MARKERS: Final = ("401", "oidc", "unauthenticated")
_IGNORED_EVENT_TYPES: Final = frozenset({"thought", "usage", "available_commands", "plan"})
_PROMPT_FILE_ARGUMENT_INDEX: Final = 2
# Grok owns this larger bound because a 600-second streamed turn can include
# substantial thought and usage NDJSON before its final answer.
GROK_CLI_TURN_OUTPUT_READ_LIMIT_BYTES: Final = 4 * 1024 * 1024

log = logging.getLogger(__name__)


class _GrokCliStreamFailure(Exception):
    """The streamed protocol named a terminal adapter failure."""

    def __init__(self, code: str) -> None:
        self.code = code


async def stream_grok_cli_turn(
    *, system: str, model: str, messages: list[dict[str, str]],
) -> AsyncIterator[StreamEvent]:
    """Yield Grok text events only after its subscription CLI accepts the turn."""
    prompt = _stdin_prompt(system, _flatten_messages("", messages)).encode()
    channel = CliLineChannel(COWRITER_GROK_CLI_LINE_CHANNEL_CAPACITY)
    deadline = time.monotonic() + COWRITER_CLI_TIMEOUT_SECONDS
    command = _build_grok_cli_command(model)
    turn_directory = tempfile.TemporaryDirectory(prefix="songmaker-grok-cli-")
    runner = asyncio.create_task(asyncio.to_thread(
        run_cli_bounded,
        command,
        stdin_payload=None,
        read="all",
        deadline=deadline,
        output_read_limit_bytes=GROK_CLI_TURN_OUTPUT_READ_LIMIT_BYTES,
        stdout_line_channel=channel,
        prompt_file_bytes=prompt,
        prompt_file_arg_index=_PROMPT_FILE_ARGUMENT_INDEX,
        cwd=turn_directory.name,
    ))
    text_chunks: list[str] = []
    saw_end = False
    error_message: str | None = None
    try:
        while True:
            item = await asyncio.to_thread(channel.receive)
            if isinstance(item, CliRunOutcome):
                outcome = item
                break
            event_type, event_data = _parse_grok_line(item)
            if saw_end:
                raise _GrokCliStreamFailure("grok_cli_stream_protocol_error")
            if event_type in {"tool_call", "tool_call_update"}:
                raise _GrokCliStreamFailure("grok_cli_tool_call_blocked")
            if event_type == "text":
                text = _text_event_data(event_data)
                text_chunks.append(text)
                yield AssistantTextEvent(text=text)
                continue
            if event_type == "end":
                _end_event_data(event_data)
                saw_end = True
                continue
            if event_type == "error":
                error_message = _error_event_data(event_data)
                channel.request_abort()
                continue
            if event_type in _IGNORED_EVENT_TYPES:
                continue
            log.warning(
                "Grok CLI emitted an unknown stream event type (type_length=%d)",
                len(event_type),
            )
            raise _GrokCliStreamFailure("grok_cli_stream_protocol_error")
        await asyncio.shield(runner)
        _raise_for_grok_outcome(outcome, saw_end, error_message)
        yield FinalEvent(text="".join(text_chunks))
    except _GrokCliStreamFailure as exc:
        channel.request_abort()
        await asyncio.shield(runner)
        raise ProviderUnavailableError("grok", exc.code) from exc
    finally:
        channel.request_abort()
        try:
            await asyncio.shield(runner)
        finally:
            turn_directory.cleanup()


def _build_grok_cli_command(model: str) -> tuple[str, ...]:
    return (
        GROK_CLI_BINARY,
        "--prompt-file",
        GROK_CLI_PROMPT_FILE_PLACEHOLDER,
        "--output-format",
        GROK_CLI_STREAMING_OUTPUT_FORMAT,
        "--deny",
        "*",
        "--max-turns",
        "1",
        "--no-subagents",
        "--disable-web-search",
        "--model",
        model,
    )


def _parse_grok_line(line: bytes) -> tuple[str, dict[str, object]]:
    try:
        parsed = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _GrokCliStreamFailure("grok_cli_stream_protocol_error") from exc
    if not isinstance(parsed, dict):
        raise _GrokCliStreamFailure("grok_cli_stream_protocol_error")
    event_type = parsed.get("type")
    if not isinstance(event_type, str):
        raise _GrokCliStreamFailure("grok_cli_stream_protocol_error")
    return event_type, parsed


def _text_event_data(event: dict[str, object]) -> str:
    data = event.get("data")
    if not isinstance(data, str):
        raise _GrokCliStreamFailure("grok_cli_stream_protocol_error")
    return data


def _end_event_data(event: dict[str, object]) -> None:
    if not isinstance(event.get("stopReason"), str):
        raise _GrokCliStreamFailure("grok_cli_stream_protocol_error")


def _error_event_data(event: dict[str, object]) -> str:
    message = event.get("message")
    if not isinstance(message, str):
        raise _GrokCliStreamFailure("grok_cli_stream_protocol_error")
    return message


def _raise_for_grok_outcome(
    outcome: CliRunOutcome,
    saw_end: bool,
    error_message: str | None,
) -> None:
    if error_message is not None or not outcome.complete or outcome.returncode != 0 or not saw_end:
        if _contains_auth_failure(error_message) or _contains_auth_failure(outcome.stderr):
            raise ProviderUnavailableError("grok", "cli_login_expired")
        log.warning(
            "Grok CLI failed (rc=%s, stderr_bytes=%d)",
            outcome.returncode,
            len(outcome.stderr.encode()),
        )
        raise ProviderUnavailableError("grok", "grok_cli_error")


def _contains_auth_failure(value: str | None) -> bool:
    return value is not None and any(marker in value.lower() for marker in _AUTH_FAILURE_MARKERS)
