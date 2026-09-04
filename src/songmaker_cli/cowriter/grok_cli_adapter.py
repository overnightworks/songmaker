"""Grok subscription CLI transport for one tool-free co-writer turn."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final
from urllib.parse import quote

from songmaker_cli.agent_cli import (
    CliLineChannel,
    CliRunOutcome,
    run_cli_bounded,
    scrubbed_env,
)
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
    ToolResultBatch,
    TransportResponse,
)

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


class GrokCliToolTransport:
    """One private, resumable Grok CLI session for the shared tool loop.

    Grok persists every headless session below its normal profile directory.
    A unique working directory gives this transport one isolated session-tree
    leaf while preserving the operator's authenticated profile.  ``aclose``
    removes that tree only after the bounded runner has reaped its process.
    """

    def __init__(self, *, model: str) -> None:
        self._model = model
        self._turn_directory = tempfile.TemporaryDirectory(prefix="songmaker-grok-cli-")
        os.chmod(self._turn_directory.name, 0o700)
        self._deadline = time.monotonic() + COWRITER_CLI_TIMEOUT_SECONDS
        self._session_id: str | None = None
        self._round_index = 0
        self._closed = False

    async def stream(
        self,
        message: InitialTurn | ToolResultBatch,
    ) -> AsyncIterator[TransportResponse]:
        """Stream one response and retain its server-issued session ID."""
        if self._closed:
            raise RuntimeError("Grok CLI tool transport is closed")
        # The canonical text-tool catalogue imports the optional MCP package.
        # Keep it on this tool-using path so tool-free workers can import this
        # adapter without that optional dependency.
        from songmaker_cli.cowriter.text_tool_protocol import (
            FinalText as ParsedFinalText,
        )
        from songmaker_cli.cowriter.text_tool_protocol import (
            TextToolCall,
            TextToolProtocolError,
            TextToolStreamParser,
        )

        try:
            prompt = _tool_transport_prompt(message)
        except TextToolProtocolError:
            raise ProviderUnavailableError(
                "grok",
                "cli",
                normalize_route_failure(SafeRouteReasonCode.TOOL_PROTOCOL_ERROR),
            ) from None
        is_resume = self._session_id is not None
        if is_resume:
            command = _build_grok_cli_tool_command(self._model, self._session_id)
        else:
            command = _build_grok_cli_tool_command(self._model)
        self._round_index += 1
        channel = CliLineChannel(COWRITER_GROK_CLI_LINE_CHANNEL_CAPACITY)
        runner = asyncio.create_task(asyncio.to_thread(
            run_cli_bounded,
            command,
            stdin_payload=None,
            read="all",
            deadline=self._deadline,
            output_read_limit_bytes=GROK_CLI_TURN_OUTPUT_READ_LIMIT_BYTES,
            stdout_line_channel=channel,
            prompt_file_bytes=prompt,
            prompt_file_arg_index=_PROMPT_FILE_ARGUMENT_INDEX,
            cwd=self._turn_directory.name,
            extra_env=_grok_cli_env(),
            unset_env=("GROK_HOME",),
        ))
        parser = TextToolStreamParser()
        saw_end = False
        error_message: str | None = None
        received_session_id: str | None = None
        started_at = time.monotonic()
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
                    text = parser.feed(_text_event_data(event_data))
                    if text:
                        yield TextDelta(text)
                    continue
                if event_type == "end":
                    _end_event_data(event_data)
                    received_session_id = _stream_session_id(event_data)
                    saw_end = True
                    continue
                if event_type == "error":
                    error_message = _error_event_data(event_data)
                    channel.request_abort()
                    continue
                if event_type in _IGNORED_EVENT_TYPES:
                    continue
                raise _GrokCliStreamFailure("grok_cli_stream_protocol_error")
            await asyncio.shield(runner)
            _raise_for_grok_outcome(outcome, saw_end, error_message)
            if received_session_id is None:
                raise _GrokCliStreamFailure("grok_cli_stream_protocol_error")
            if is_resume and received_session_id != self._session_id:
                raise _GrokCliStreamFailure("grok_cli_stream_protocol_error")
            self._session_id = received_session_id
            parsed = parser.finish()
            if isinstance(parsed, TextToolCall):
                call = ToolCall(str(uuid.uuid4()), parsed.name, parsed.arguments)
                _log_tool_round(self._round_index, self._session_id, started_at, call.name)
                yield ToolCallBatch((call,))
            elif isinstance(parsed, ParsedFinalText):
                _log_tool_round(self._round_index, self._session_id, started_at, None)
                yield FinalText(parsed.text)
            else:  # pragma: no cover - TypeAlias keeps this branch unreachable.
                raise _GrokCliStreamFailure("grok_cli_stream_protocol_error")
        except TextToolProtocolError:
            channel.request_abort()
            await asyncio.shield(runner)
            raise ProviderUnavailableError(
                "grok",
                "cli",
                normalize_route_failure(SafeRouteReasonCode.TOOL_PROTOCOL_ERROR),
            ) from None
        except _GrokCliStreamFailure as exc:
            channel.request_abort()
            await asyncio.shield(runner)
            reason = (
                SafeRouteReasonCode.TOOL_PROTOCOL_ERROR
                if exc.code == "grok_cli_tool_call_blocked"
                else SafeRouteReasonCode.CLI_PROTOCOL_ERROR
            )
            raise ProviderUnavailableError(
                "grok",
                "cli",
                normalize_route_failure(reason),
            ) from None
        finally:
            channel.request_abort()
            await asyncio.shield(runner)

    async def aclose(self) -> None:
        """Remove the turn's private CWD and only its matching Grok sessions."""
        if self._closed:
            return
        self._closed = True
        try:
            _remove_grok_sessions_for_cwd(self._turn_directory.name)
        finally:
            self._turn_directory.cleanup()


async def stream_grok_cli_turn(
    *, system: str, model: str, messages: list[dict[str, str]],
) -> AsyncIterator[StreamEvent]:
    """Yield Grok text events only after its subscription CLI accepts the turn."""
    prompt = _stdin_prompt(system, _flatten_messages("", messages)).encode()
    channel = CliLineChannel(COWRITER_GROK_CLI_LINE_CHANNEL_CAPACITY)
    deadline = time.monotonic() + COWRITER_CLI_TIMEOUT_SECONDS
    command = _build_grok_cli_command(model)
    turn_directory = tempfile.TemporaryDirectory(prefix="songmaker-grok-cli-")
    os.chmod(turn_directory.name, 0o700)
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
        extra_env=_grok_cli_env(),
        unset_env=("GROK_HOME",),
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
            raise _GrokCliStreamFailure("grok_cli_stream_protocol_error")
        await asyncio.shield(runner)
        _raise_for_grok_outcome(outcome, saw_end, error_message)
        yield FinalEvent(text="".join(text_chunks))
    except _GrokCliStreamFailure as exc:
        channel.request_abort()
        await asyncio.shield(runner)
        reason = (
            SafeRouteReasonCode.ROUTE_TEXT_ONLY
            if exc.code == "grok_cli_tool_call_blocked"
            else SafeRouteReasonCode.CLI_PROTOCOL_ERROR
        )
        raise ProviderUnavailableError(
            "grok",
            "cli",
            normalize_route_failure(reason),
        ) from None
    finally:
        channel.request_abort()
        try:
            await asyncio.shield(runner)
        finally:
            try:
                _remove_grok_sessions_for_cwd(turn_directory.name)
            finally:
                turn_directory.cleanup()


def _tool_transport_prompt(message: InitialTurn | ToolResultBatch) -> bytes:
    from songmaker_cli.cowriter.text_tool_protocol import (
        TextToolProtocolError,
        render_tool_result,
    )

    if isinstance(message, InitialTurn):
        return _stdin_prompt(
            message.system,
            _flatten_messages("", message.messages),
        ).encode()
    if len(message.results) != 1:
        raise TextToolProtocolError()
    result = message.results[0]
    try:
        value = json.loads(result.content)
    except json.JSONDecodeError:
        value = result.content
    return render_tool_result(value).encode()


def _build_grok_cli_tool_command(
    model: str,
    session_id: str | None = None,
) -> tuple[str, ...]:
    command = [
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
    ]
    if session_id is not None:
        command.extend(("--resume", session_id))
    return tuple(command)


def _stream_session_id(event: dict[str, object]) -> str:
    session_id = event.get("sessionId")
    if not isinstance(session_id, str):
        raise _GrokCliStreamFailure("grok_cli_stream_protocol_error")
    try:
        uuid.UUID(session_id)
    except ValueError as exc:
        raise _GrokCliStreamFailure("grok_cli_stream_protocol_error") from exc
    return session_id


def _remove_grok_sessions_for_cwd(cwd: str) -> None:
    """Delete the session subtree selected by this private CWD only."""
    session_tree = Path.home() / ".grok" / "sessions" / quote(cwd, safe="")
    if session_tree.exists():
        shutil.rmtree(session_tree)


def _grok_cli_env() -> dict[str, str]:
    """Keep Grok's authenticated profile while forbidding profile replacement."""
    environment = scrubbed_env()
    environment.pop("GROK_HOME", None)
    return environment


def _log_tool_round(
    round_index: int,
    session_id: str,
    started_at: float,
    tool_name: str | None,
) -> None:
    duration_ms = round((time.monotonic() - started_at) * 1000)
    log.info(
        "Co-writer Grok CLI provider=grok route=cli round=%s session=%s "
        "duration_ms=%s tool=%s is_error=%s",
        round_index,
        session_id,
        duration_ms,
        tool_name or "none",
        False,
    )


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
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = None
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
            raise ProviderUnavailableError(
                "grok",
                "cli",
                normalize_route_failure(SafeRouteReasonCode.CLI_AUTH_REJECTED),
            )
        raise ProviderUnavailableError(
            "grok",
            "cli",
            normalize_route_failure(SafeRouteReasonCode.CLI_PROTOCOL_ERROR),
        )


def _contains_auth_failure(value: str | None) -> bool:
    return value is not None and any(marker in value.lower() for marker in _AUTH_FAILURE_MARKERS)
