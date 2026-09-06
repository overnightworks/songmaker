"""The Codex subscription CLI transport for one co-writer tool-loop turn."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agent_providers.claude.provider import (
    flatten_messages,
    stdin_prompt,
)
from agent_providers.codex.pool import (
    CodexProcessKind,
    CodexProcessReservation,
    get_codex_process_pool,
)
from agent_providers.codex.protocol import (
    BLOCKED_ITEM_TYPES,
    CODEX_APPROVAL_POLICY_NEVER_CONFIG,
    CODEX_CLI_LINE_CHANNEL_CAPACITY,
    CODEX_CLI_TURN_OUTPUT_READ_LIMIT_BYTES,
    CODEX_EMPTY_MCP_SERVERS_CONFIG,
    CODEX_ITEM_COMPLETED_EVENT,
    INFORMATIONAL_ITEM_TYPES,
    ITEM_EVENT_TYPES,
    CodexCliStreamFailure,
    CodexLoginMirrorError,
    codex_cli_failure_reason,
    copy_codex_login_mirror,
    error_item_message,
    event_item,
    event_item_type,
    failed_turn_message,
    parse_codex_line,
    run_reserved_codex_cli,
    top_level_error_message,
)
from agent_providers.config import current_config
from agent_providers.constants import COWRITER_CLI_TIMEOUT_SECONDS
from agent_providers.errors import (
    CodexProcessPoolSaturatedError,
    ProviderUnavailableError,
    SafeRouteReasonCode,
    normalize_route_failure,
)
from agent_providers.process import (
    CliLineChannel,
    CliRunOutcome,
    CliRunReason,
    scrubbed_env,
)
from agent_providers.text_tool_protocol import (
    FinalText as ParsedFinalText,
)
from agent_providers.text_tool_protocol import (
    TextToolCall,
    TextToolProtocolError,
    TextToolStreamParser,
    render_tool_result,
)
from agent_providers.tool_loop import (
    FinalText,
    InitialTurn,
    TextDelta,
    ToolCall,
    ToolCallBatch,
    ToolResultBatch,
    TransportResponse,
)
from agent_providers.tools import ToolCatalog

CODEX_TOOL_TURN_DIRECTORY_PREFIX: Final = "songmaker-codex-tool-"
_CODEX_TOOL_ISOLATION_CONFIGS: Final = (
    CODEX_APPROVAL_POLICY_NEVER_CONFIG,
    CODEX_EMPTY_MCP_SERVERS_CONFIG,
    "features.shell_tool=false",
    "features.unified_exec=false",
    "features.browser_use=false",
    "features.computer_use=false",
    "features.multi_agent=false",
    "features.image_generation=false",
    "features.plugins=false",
    "features.hooks=false",
    'web_search="disabled"',
    "features.code_mode_host=false",
    "features.code_mode=false",
    "features.code_mode_only=false",
)
# Codex appends version-specific remediation after this stable isolation notice.
_CODE_MODE_HOST_DISABLED_ISOLATION_NOTICE_PREFIX: Final = (
    "Code Mode is unavailable because code-mode host is disabled"
)
log = logging.getLogger(__name__)


@dataclass
class _CodexToolRoundState:
    """Protocol state accumulated while receiving one Codex CLI round."""

    saw_success: bool = False
    error_message: str | None = None
    received_thread_id: str | None = None


class CodexCliToolTransport:
    """One private, resumable Codex CLI session for the shared tool loop.

    Codex receives each round on stdin. Its private home and persisted session
    are siblings of an empty private working directory and removed by
    :meth:`aclose`.
    """

    def __init__(self, *, model: str, catalog: ToolCatalog) -> None:
        self._model = model
        self._catalog = catalog
        self._turn_directory = tempfile.TemporaryDirectory(
            prefix=CODEX_TOOL_TURN_DIRECTORY_PREFIX,
            dir=current_config().cli_working_directory_root,
        )
        os.chmod(self._turn_directory.name, 0o700)
        turn_root = Path(self._turn_directory.name)
        self._work_directory = turn_root / "work"
        self._codex_home = turn_root / "codex-home"
        self._work_directory.mkdir(mode=0o700)
        self._codex_home.mkdir(mode=0o700)
        try:
            copy_codex_login_mirror(self._codex_home)
        except CodexLoginMirrorError:
            self._turn_directory.cleanup()
            raise ProviderUnavailableError(
                "codex",
                "cli",
                normalize_route_failure(SafeRouteReasonCode.CLI_AUTH_REJECTED),
            ) from None
        self._deadline = time.monotonic() + COWRITER_CLI_TIMEOUT_SECONDS
        self._thread_id: str | None = None
        self._round_index = 0
        self._closed = False

    async def stream(
        self,
        message: InitialTurn | ToolResultBatch,
    ) -> AsyncIterator[TransportResponse]:
        """Stream one response, retaining only the server-issued thread ID."""
        if self._closed:
            raise RuntimeError("Codex CLI tool transport is closed")
        try:
            prompt = _tool_transport_prompt(self._catalog, message)
        except TextToolProtocolError:
            raise ProviderUnavailableError(
                "codex",
                "cli",
                normalize_route_failure(SafeRouteReasonCode.TOOL_PROTOCOL_ERROR),
            ) from None
        is_resume = self._thread_id is not None
        command = _build_codex_tool_command(
            self._model,
            thread_id=self._thread_id,
        )
        self._round_index += 1
        channel = CliLineChannel(CODEX_CLI_LINE_CHANNEL_CAPACITY)
        try:
            reservation = get_codex_process_pool().reserve(CodexProcessKind.TEXT)
        except CodexProcessPoolSaturatedError as exc:
            raise ProviderUnavailableError(
                "codex",
                "cli",
                normalize_route_failure(SafeRouteReasonCode.CLI_CAPACITY_EXHAUSTED),
            ) from exc
        runner = asyncio.create_task(
            asyncio.to_thread(
                _run_codex_tool_round,
                reservation=reservation,
                command=command,
                prompt=prompt,
                deadline=self._deadline,
                channel=channel,
                cwd=str(self._work_directory),
                codex_home=self._codex_home,
            )
        )
        parser = TextToolStreamParser(self._catalog)
        state = _CodexToolRoundState()
        started_at = time.monotonic()
        try:
            while True:
                item = await asyncio.to_thread(channel.receive)
                if isinstance(item, CliRunOutcome):
                    outcome = item
                    break
                event_type, event = parse_codex_line(item)
                text = _consume_codex_tool_event(
                    event_type,
                    event,
                    is_resume=is_resume,
                    expected_thread_id=self._thread_id,
                    parser=parser,
                    state=state,
                    channel=channel,
                )
                if text:
                    yield TextDelta(text)
            await asyncio.shield(runner)
            response, thread_id = _finish_codex_tool_round(
                outcome,
                is_resume=is_resume,
                state=state,
                parser=parser,
                round_index=self._round_index,
                started_at=started_at,
            )
            if thread_id is not None:
                self._thread_id = thread_id
            yield response
        except TextToolProtocolError:
            channel.request_abort()
            await asyncio.shield(runner)
            raise ProviderUnavailableError(
                "codex",
                "cli",
                normalize_route_failure(SafeRouteReasonCode.TOOL_PROTOCOL_ERROR),
            ) from None
        except CodexCliStreamFailure as exc:
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
            ) from None
        finally:
            channel.request_abort()
            await asyncio.shield(runner)

    async def aclose(self) -> None:
        """Remove all private session and prompt material after reaping a round."""
        if self._closed:
            return
        self._closed = True
        await asyncio.to_thread(self._turn_directory.cleanup)


def _build_codex_tool_command(
    model: str,
    *,
    thread_id: str | None = None,
) -> tuple[str, ...]:
    """Build a read-only start or resume command for one tool-loop round.

    Codex CLI 0.147 exposes ``--sandbox`` only on ``exec``.  ``exec resume``
    accepts the equivalent TOML override instead, so the sandbox is pinned on
    every round even though the command spelling differs.
    """
    common = (
        "--json",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        *(part for config in _CODEX_TOOL_ISOLATION_CONFIGS for part in ("-c", config)),
        "-c",
        'sandbox_mode="read-only"',
        "--model",
        model,
    )
    binary = current_config().codex_cli_binary
    if thread_id is None:
        return (
            binary,
            "exec",
            "--sandbox",
            "read-only",
            *common,
            "-",
        )
    return (
        binary,
        "exec",
        "resume",
        *common,
        thread_id,
        "-",
    )


def _run_codex_tool_round(
    *,
    reservation: CodexProcessReservation,
    command: tuple[str, ...],
    prompt: bytes,
    deadline: float,
    channel: CliLineChannel,
    cwd: str,
    codex_home: Path,
) -> CliRunOutcome:
    """Run one round from stdin and reap its reservation."""
    try:
        return run_reserved_codex_cli(
            reservation,
            command,
            stdin_payload=prompt,
            read="all",
            deadline=deadline,
            output_read_limit_bytes=CODEX_CLI_TURN_OUTPUT_READ_LIMIT_BYTES,
            stdout_line_channel=channel,
            cwd=cwd,
            extra_env=_codex_cli_env(codex_home),
        )
    except Exception as exc:
        get_codex_process_pool().abandon_unspawned(reservation)
        outcome = CliRunOutcome(
            started=False,
            spawn_error=exc,
            returncode=None,
            stdout="",
            stderr="",
            complete=False,
            became_zombie=False,
            reason=CliRunReason.IO_ERROR,
            io_error=exc if isinstance(exc, OSError) else None,
        )
        channel._close(outcome)
        return outcome


def _tool_transport_prompt(
    catalog: ToolCatalog,
    message: InitialTurn | ToolResultBatch,
) -> bytes:
    """Render one initial prompt or exactly one completed tool result."""
    if isinstance(message, InitialTurn):
        return stdin_prompt(
            message.system,
            flatten_messages("", message.messages),
        ).encode()
    if len(message.results) != 1:
        raise TextToolProtocolError()
    result = message.results[0]
    try:
        value = json.loads(result.content)
    except json.JSONDecodeError:
        value = result.content
    return render_tool_result(catalog, value).encode()


def _consume_codex_tool_event(
    event_type: str,
    event: dict[str, object],
    *,
    is_resume: bool,
    expected_thread_id: str | None,
    parser: TextToolStreamParser,
    state: _CodexToolRoundState,
    channel: CliLineChannel,
) -> str | None:
    """Apply one Codex event and return any safe assistant-text delta."""
    if state.saw_success:
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error")
    if event_type == "thread.started":
        _record_codex_thread_id(
            event,
            is_resume=is_resume,
            expected_thread_id=expected_thread_id,
            state=state,
        )
        return None
    if event_type == "turn.started":
        return None
    if event_type in ITEM_EVENT_TYPES:
        return _consume_codex_item_event(event_type, event, parser, state, channel)
    if event_type == "turn.completed":
        _completed_turn(event)
        state.saw_success = True
        return None
    if event_type == "error":
        state.error_message = top_level_error_message(event)
        channel.request_abort()
        return None
    if event_type == "turn.failed":
        state.error_message = failed_turn_message(event)
        channel.request_abort()
        return None
    raise CodexCliStreamFailure("codex_cli_stream_protocol_error")


def _record_codex_thread_id(
    event: dict[str, object],
    *,
    is_resume: bool,
    expected_thread_id: str | None,
    state: _CodexToolRoundState,
) -> None:
    thread_id = _thread_started_id(event)
    if state.received_thread_id is not None or (is_resume and thread_id != expected_thread_id):
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error")
    state.received_thread_id = thread_id


def _consume_codex_item_event(
    event_type: str,
    event: dict[str, object],
    parser: TextToolStreamParser,
    state: _CodexToolRoundState,
    channel: CliLineChannel,
) -> str | None:
    item_type = event_item_type(event)
    if item_type in BLOCKED_ITEM_TYPES:
        raise CodexCliStreamFailure("codex_cli_tool_call_blocked")
    if event_type == CODEX_ITEM_COMPLETED_EVENT and item_type == "error":
        completed_error = error_item_message(event)
        if _is_code_mode_host_disabled_isolation_notice(completed_error):
            log.info("Codex CLI ignored its code-mode-host isolation notice")
            return None
        state.error_message = completed_error
        channel.request_abort()
        return None
    if item_type not in INFORMATIONAL_ITEM_TYPES:
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error")
    if event_type == CODEX_ITEM_COMPLETED_EVENT and item_type == "agent_message":
        return parser.feed(_completed_agent_message(event))
    return None


def _finish_codex_tool_round(
    outcome: CliRunOutcome,
    *,
    is_resume: bool,
    state: _CodexToolRoundState,
    parser: TextToolStreamParser,
    round_index: int,
    started_at: float,
) -> tuple[TransportResponse, str | None]:
    """Validate one completed Codex round and produce its terminal response."""
    _raise_for_codex_outcome(outcome, state.saw_success, state.error_message, None)
    if not is_resume and state.received_thread_id is None:
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error")
    parsed = parser.finish()
    if isinstance(parsed, TextToolCall):
        call = ToolCall(str(uuid.uuid4()), parsed.name, parsed.arguments)
        _log_codex_tool_round(round_index, started_at, call.name)
        return ToolCallBatch((call,)), state.received_thread_id
    if isinstance(parsed, ParsedFinalText):
        _log_codex_tool_round(round_index, started_at, None)
        return FinalText(parsed.text), state.received_thread_id
    raise CodexCliStreamFailure("codex_cli_stream_protocol_error")


def _codex_cli_env(codex_home: Path) -> dict[str, str]:
    """Pass a scrubbed environment and only this turn's private Codex home."""
    environment = scrubbed_env()
    environment["CODEX_HOME"] = str(codex_home)
    return environment


def _thread_started_id(event: dict[str, object]) -> str:
    thread_id = event.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error")
    try:
        return str(uuid.UUID(thread_id))
    except ValueError as exc:
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error") from exc


def _log_codex_tool_round(
    round_index: int,
    started_at: float,
    tool_name: str | None,
) -> None:
    duration_ms = round((time.monotonic() - started_at) * 1000)
    log.info(
        "Co-writer Codex CLI provider=codex route=cli round=%s duration_ms=%s tool=%s is_error=%s",
        round_index,
        duration_ms,
        tool_name or "none",
        False,
    )


def _completed_agent_message(event: dict[str, object]) -> str:
    item = event_item(event)
    text = item.get("text")
    if not isinstance(text, str):
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error")
    return text


def _is_code_mode_host_disabled_isolation_notice(message: str) -> bool:
    """Recognize the one Codex notice caused by this adapter's isolation."""
    return message.startswith(_CODE_MODE_HOST_DISABLED_ISOLATION_NOTICE_PREFIX)


def _completed_turn(event: dict[str, object]) -> None:
    if not isinstance(event.get("usage"), dict):
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error")


def _raise_for_codex_outcome(
    outcome: CliRunOutcome,
    saw_success: bool,
    error_message: str | None,
    completed_error_item_message: str | None,
) -> None:
    if saw_success:
        if not outcome.complete or outcome.returncode != 0:
            _raise_codex_cli_failure(outcome, None)
        return
    if completed_error_item_message is not None:
        _raise_codex_cli_failure(outcome, completed_error_item_message)
    if error_message is not None:
        _raise_codex_cli_failure(outcome, error_message)
    if not outcome.complete or outcome.returncode != 0:
        _raise_codex_cli_failure(outcome, None)
    raise ProviderUnavailableError(
        "codex",
        "cli",
        normalize_route_failure(SafeRouteReasonCode.CLI_PROTOCOL_ERROR),
    )


def _raise_codex_cli_failure(outcome: CliRunOutcome, error_message: str | None) -> None:
    log.warning(
        "Codex CLI failed (rc=%s, stderr_bytes=%d)",
        outcome.returncode,
        len(outcome.stderr.encode()),
    )
    raise ProviderUnavailableError(
        "codex",
        "cli",
        normalize_route_failure(codex_cli_failure_reason(error_message, outcome.stderr)),
    )


