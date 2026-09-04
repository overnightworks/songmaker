"""Codex subscription CLI transport for one tool-free co-writer turn."""

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
from songmaker_cli.constants import CODEX_CLI_BINARY, COWRITER_CLI_TIMEOUT_SECONDS
from songmaker_cli.cowriter.errors import (
    ProviderUnavailableError,
    SafeRouteReasonCode,
    normalize_route_failure,
)

CODEX_CLI_LINE_CHANNEL_CAPACITY: Final = 64
CODEX_CLI_TURN_OUTPUT_READ_LIMIT_BYTES: Final = 4 * 1024 * 1024
_AUTH_FAILURE_MARKERS: Final = ("401", "unauthorized", "unauthenticated")
_BLOCKED_ITEM_TYPES: Final = frozenset({
    "command_execution", "mcp_tool_call", "web_search", "file_change",
})

log = logging.getLogger(__name__)


class _CodexCliStreamFailure(Exception):
    """The streamed protocol named a terminal adapter failure."""

    def __init__(self, code: str) -> None:
        self.code = code


async def stream_codex_cli_turn(
    *, system: str, model: str, messages: list[dict[str, str]],
) -> AsyncIterator[StreamEvent]:
    """Yield Codex text events only after its subscription CLI accepts the turn."""
    prompt = _stdin_prompt(system, _flatten_messages("", messages)).encode()
    channel = CliLineChannel(CODEX_CLI_LINE_CHANNEL_CAPACITY)
    deadline = time.monotonic() + COWRITER_CLI_TIMEOUT_SECONDS
    turn_directory = tempfile.TemporaryDirectory(prefix="songmaker-codex-cli-")
    runner = asyncio.create_task(asyncio.to_thread(
        run_cli_bounded,
        _build_codex_cli_command(model),
        stdin_payload=prompt,
        read="all",
        deadline=deadline,
        output_read_limit_bytes=CODEX_CLI_TURN_OUTPUT_READ_LIMIT_BYTES,
        stdout_line_channel=channel,
        cwd=turn_directory.name,
    ))
    text_chunks: list[str] = []
    saw_success = False
    error_message: str | None = None
    try:
        while True:
            line_or_outcome = await asyncio.to_thread(channel.receive)
            if isinstance(line_or_outcome, CliRunOutcome):
                outcome = line_or_outcome
                break
            if saw_success:
                raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
            event_type, event = _parse_codex_line(line_or_outcome)
            if event_type in {"thread.started", "turn.started"}:
                continue
            if event_type == "item.completed":
                item_type, text = _completed_item(event)
                if item_type == "agent_message":
                    text_chunks.append(text)
                    yield AssistantTextEvent(text=text)
                    continue
                if item_type == "reasoning":
                    continue
                if item_type in _BLOCKED_ITEM_TYPES:
                    raise _CodexCliStreamFailure("codex_cli_tool_call_blocked")
                raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
            if event_type.startswith("item."):
                item_type = _item_type(event)
                if item_type in _BLOCKED_ITEM_TYPES:
                    raise _CodexCliStreamFailure("codex_cli_tool_call_blocked")
                raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
            if event_type == "turn.completed":
                _completed_turn(event)
                saw_success = True
                continue
            if event_type == "error":
                error_message = _top_level_error_message(event)
                channel.request_abort()
                continue
            if event_type == "turn.failed":
                error_message = _failed_turn_message(event)
                channel.request_abort()
                continue
            raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
        await asyncio.shield(runner)
        _raise_for_codex_outcome(outcome, saw_success, error_message)
        yield FinalEvent(text="".join(text_chunks))
    except _CodexCliStreamFailure as exc:
        channel.request_abort()
        await asyncio.shield(runner)
        reason = (
            SafeRouteReasonCode.TOOL_EXECUTION_FAILED
            if exc.code == "codex_cli_tool_call_blocked"
            else SafeRouteReasonCode.CLI_PROTOCOL_ERROR
        )
        raise ProviderUnavailableError(
            "codex",
            "cli",
            normalize_route_failure(reason),
        ) from exc
    finally:
        channel.request_abort()
        try:
            await asyncio.shield(runner)
        finally:
            turn_directory.cleanup()


def _build_codex_cli_command(model: str) -> tuple[str, ...]:
    """Return the fixed, tool-free Codex command for a single streamed turn."""
    return (
        CODEX_CLI_BINARY,
        "exec",
        "--json",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "--ephemeral",
        "-c",
        'approval_policy="never"',
        "-c",
        "mcp_servers={}",
        "--model",
        model,
        "-",
    )


def _parse_codex_line(line: bytes) -> tuple[str, dict[str, object]]:
    try:
        event = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error") from exc
    if not isinstance(event, dict):
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
    event_type = event.get("type")
    if not isinstance(event_type, str):
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
    return event_type, event


def _completed_item(event: dict[str, object]) -> tuple[str, str]:
    item = _item(event)
    item_type = _item_type(event)
    if item_type == "agent_message":
        text = item.get("text")
        if not isinstance(text, str):
            raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
        return item_type, text
    return item_type, ""


def _item_type(event: dict[str, object]) -> str:
    item_type = _item(event).get("type")
    if not isinstance(item_type, str):
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
    return item_type


def _item(event: dict[str, object]) -> dict[str, object]:
    item = event.get("item")
    if not isinstance(item, dict):
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
    return item


def _completed_turn(event: dict[str, object]) -> None:
    if not isinstance(event.get("usage"), dict):
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")


def _top_level_error_message(event: dict[str, object]) -> str:
    message = event.get("message")
    if not isinstance(message, str):
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
    return message


def _failed_turn_message(event: dict[str, object]) -> str:
    error = event.get("error")
    if not isinstance(error, dict):
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
    message = error.get("message")
    if not isinstance(message, str):
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
    return message


def _raise_for_codex_outcome(
    outcome: CliRunOutcome,
    saw_success: bool,
    error_message: str | None,
) -> None:
    if error_message is not None:
        _raise_codex_cli_failure(outcome, error_message)
    if not outcome.complete or outcome.returncode != 0:
        _raise_codex_cli_failure(outcome, None)
    if not saw_success:
        raise ProviderUnavailableError(
            "codex",
            "cli",
            normalize_route_failure(SafeRouteReasonCode.CLI_PROTOCOL_ERROR),
        )


def _raise_codex_cli_failure(outcome: CliRunOutcome, error_message: str | None) -> None:
    if _contains_auth_failure(error_message) or _contains_auth_failure(outcome.stderr):
        raise ProviderUnavailableError(
            "codex",
            "cli",
            normalize_route_failure(SafeRouteReasonCode.CLI_AUTH_REJECTED),
        )
    log.warning(
        "Codex CLI failed (rc=%s, stderr_bytes=%d)",
        outcome.returncode,
        len(outcome.stderr.encode()),
    )
    raise ProviderUnavailableError(
        "codex",
        "cli",
        normalize_route_failure(SafeRouteReasonCode.CLI_PROTOCOL_ERROR),
    )


def _contains_auth_failure(value: str | None) -> bool:
    return value is not None and any(marker in value.lower() for marker in _AUTH_FAILURE_MARKERS)
