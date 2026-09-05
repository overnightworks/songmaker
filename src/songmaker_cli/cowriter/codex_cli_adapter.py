"""Codex subscription CLI transports for co-writer tools and cover images."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Final

from PIL import Image, ImageOps

from songmaker_cli.agent_cli import (
    CliLineChannel,
    CliRunOutcome,
    CliRunReason,
    run_cli_bounded,
    scrubbed_env,
)
from songmaker_cli.claude.provider import (
    _flatten_messages,
    _stdin_prompt,
)
from songmaker_cli.constants import (
    CODEX_CLI_AUTH_FILE,
    CODEX_CLI_BINARY,
    CODEX_CODE_MODE_HOST_BINARY,
    CODEX_RESOURCES_DIRECTORY,
    COVER_MAX_PIXELS,
    COVER_PNG_MAGIC,
    COWRITER_CLI_TIMEOUT_SECONDS,
)
from songmaker_cli.cowriter.codex_process_pool import (
    CodexProcessKind,
    CodexProcessReservation,
    get_codex_process_pool,
)
from songmaker_cli.cowriter.errors import (
    CodexProcessPoolSaturatedError,
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

CODEX_CLI_LINE_CHANNEL_CAPACITY: Final = 64
CODEX_CLI_TURN_OUTPUT_READ_LIMIT_BYTES: Final = 4 * 1024 * 1024
_AUTH_FAILURE_MARKERS: Final = ("401", "unauthorized", "unauthenticated")
# Codex appends version-specific remediation after this stable isolation notice.
_CODE_MODE_HOST_DISABLED_ISOLATION_NOTICE_PREFIX: Final = (
    "Code Mode is unavailable because code-mode host is disabled"
)
_CODEX_APPROVAL_POLICY_NEVER_CONFIG: Final = 'approval_policy="never"'
_CODEX_EMPTY_MCP_SERVERS_CONFIG: Final = "mcp_servers={}"
_CODEX_ITEM_COMPLETED_EVENT: Final = "item.completed"
_BLOCKED_ITEM_TYPES: Final = frozenset(
    {
        "collab_agent_tool_call",
        "command_execution",
        "file_change",
        "image_generation",
        "mcp_tool_call",
        "web_search",
    }
)
_CODEX_CLI_ISOLATION_ARGS: Final = (
    "--skip-git-repo-check",
    "--ignore-user-config",
    "--ignore-rules",
    "--ephemeral",
    "--disable",
    "code_mode_host",
    "--disable",
    "code_mode",
    "--disable",
    "code_mode_only",
    "-c",
    _CODEX_APPROVAL_POLICY_NEVER_CONFIG,
    "-c",
    _CODEX_EMPTY_MCP_SERVERS_CONFIG,
)
_CODEX_TOOL_ISOLATION_CONFIGS: Final = (
    _CODEX_APPROVAL_POLICY_NEVER_CONFIG,
    _CODEX_EMPTY_MCP_SERVERS_CONFIG,
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
_CODEX_IMAGE_ISOLATION_ARGS: Final = (
    "--skip-git-repo-check",
    "--ignore-user-config",
    "--ignore-rules",
    "--ephemeral",
    "--enable",
    "code_mode_host",
    "--disable",
    "code_mode",
    "--disable",
    "code_mode_only",
    "-c",
    _CODEX_APPROVAL_POLICY_NEVER_CONFIG,
    "-c",
    _CODEX_EMPTY_MCP_SERVERS_CONFIG,
    "-c",
    'web_search="disabled"',
)
_INFORMATIONAL_ITEM_TYPES: Final = frozenset(
    {
        "agent_message",
        "reasoning",
        "todo_list",
    }
)
_ITEM_EVENT_TYPES: Final = frozenset(
    {
        "item.started",
        "item.updated",
        _CODEX_ITEM_COMPLETED_EVENT,
    }
)
_INFORMATIONAL_EVENT_TYPES: Final = frozenset({"thread.started", "turn.started"})
log = logging.getLogger(__name__)


class _CodexCliStreamFailure(Exception):
    """The streamed protocol named a terminal adapter failure."""

    def __init__(self, code: str) -> None:
        self.code = code


class _CodexLoginMirrorError(Exception):
    """The redacted Codex login mirror cannot start an isolated CLI."""


class CodexImageError(Exception):
    """A redacted failure while producing an album-cover suggestion."""


class CodexImageLoginError(CodexImageError):
    """The isolated Codex CLI home has no usable login mirror."""


class ImageToolBlockedError(CodexImageError):
    """The CLI reported a tool other than the sole permitted image tool."""


class CodexImageArtifactError(CodexImageError):
    """The isolated run did not leave one usable PNG artifact."""


class CodexImageNotCreatedError(CodexImageError):
    """The completed Codex turn did not create an image artifact."""


class CodexImageTimeoutError(CodexImageError):
    """The bounded CLI call exceeded its image-generation deadline."""


class CodexImageCliError(CodexImageError):
    """The CLI ended without a verified successful image result."""


@dataclass
class _CodexToolRoundState:
    """Protocol state accumulated while receiving one Codex CLI round."""

    saw_success: bool = False
    error_message: str | None = None
    received_thread_id: str | None = None


def codex_cover_image_capability_is_available() -> bool:
    """Whether this process has every mounted dependency for a cover image turn."""
    code_mode_host = Path(CODEX_CODE_MODE_HOST_BINARY)
    resources = Path(CODEX_RESOURCES_DIRECTORY)
    return (
        shutil.which(CODEX_CLI_BINARY) is not None
        and code_mode_host.is_file()
        and os.access(code_mode_host, os.X_OK)
        and resources.is_dir()
    )


class CodexCliToolTransport:
    """One private, resumable Codex CLI session for the shared tool loop.

    Codex receives each round on stdin. Its private home and persisted session
    are siblings of an empty private working directory and removed by
    :meth:`aclose`.
    """

    def __init__(self, *, model: str) -> None:
        self._model = model
        self._turn_directory = tempfile.TemporaryDirectory(prefix="songmaker-codex-tool-")
        os.chmod(self._turn_directory.name, 0o700)
        turn_root = Path(self._turn_directory.name)
        self._work_directory = turn_root / "work"
        self._codex_home = turn_root / "codex-home"
        self._work_directory.mkdir(mode=0o700)
        self._codex_home.mkdir(mode=0o700)
        try:
            _copy_codex_login_mirror(self._codex_home)
        except _CodexLoginMirrorError:
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
        from songmaker_cli.cowriter.text_tool_protocol import (
            TextToolProtocolError,
            TextToolStreamParser,
        )

        try:
            prompt = _tool_transport_prompt(message)
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
        parser = TextToolStreamParser()
        state = _CodexToolRoundState()
        started_at = time.monotonic()
        try:
            while True:
                item = await asyncio.to_thread(channel.receive)
                if isinstance(item, CliRunOutcome):
                    outcome = item
                    break
                event_type, event = _parse_codex_line(item)
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


def generate_codex_cover_image(
    prompt: str,
    *,
    deadline: float,
    abort_signal: threading.Event | None = None,
) -> bytes:
    """Run one isolated Codex image turn and return its normalized PNG.

    The image route deliberately owns neither credentials nor process control:
    its caller has already selected the Codex CLI route, and every process is
    spawned through ``run_cli_bounded``.  Its temporary ``CODEX_HOME`` is the
    only place where a generated artifact may be discovered.
    """
    with tempfile.TemporaryDirectory(prefix="songmaker-cover-codex-") as directory:
        root = Path(directory)
        work_dir = root / "work"
        codex_home = root / "codex-home"
        root.chmod(0o700)
        work_dir.mkdir(mode=0o700)
        codex_home.mkdir(mode=0o700)
        try:
            _copy_codex_login_mirror(codex_home)
        except _CodexLoginMirrorError as exc:
            raise CodexImageLoginError() from exc
        outcome = _run_codex_image_cli(
            prompt=prompt,
            deadline=deadline,
            codex_home=codex_home,
            work_dir=work_dir,
            abort_signal=abort_signal,
        )
        _raise_for_codex_image_outcome(outcome)
        _validate_codex_image_events(
            outcome.stdout,
            codex_home=codex_home,
        )
        artifact = _find_only_generated_png(codex_home)
        return _normalize_generated_png(artifact)


def _run_codex_image_cli(
    *,
    prompt: str,
    deadline: float,
    codex_home: Path,
    work_dir: Path,
    abort_signal: threading.Event | None = None,
) -> CliRunOutcome:
    """Reap the CLI promptly when its streamed events leave the image gate."""
    channel = CliLineChannel(CODEX_CLI_LINE_CHANNEL_CAPACITY)
    event_gate = _CodexImageEventGate(codex_home=codex_home)
    reservation = get_codex_process_pool().reserve(CodexProcessKind.COVER)

    def run() -> None:
        result = _run_reserved_codex_cli(
            reservation,
            _build_codex_image_command(),
            stdin_payload=prompt.encode("utf-8"),
            read="all",
            deadline=deadline,
            output_read_limit_bytes=CODEX_CLI_TURN_OUTPUT_READ_LIMIT_BYTES,
            stdout_line_channel=channel,
            cwd=str(work_dir.resolve()),
            extra_env={"CODEX_HOME": str(codex_home.resolve())},
        )
        channel._close(result)

    runner = threading.Thread(target=run, daemon=True)
    runner.start()
    try:
        while True:
            if abort_signal is not None and abort_signal.is_set():
                channel.request_abort()
            try:
                line_or_outcome = channel.receive(timeout=0.05)
            except TimeoutError:
                continue
            if isinstance(line_or_outcome, CliRunOutcome):
                return line_or_outcome
            try:
                event_gate.accept(line_or_outcome)
            except ImageToolBlockedError:
                channel.request_abort()
                runner.join()
                raise
            except CodexImageCliError:
                # A valid partial stream has no completed turn yet. Its full
                # transcript is checked below after the child has been reaped.
                continue
    finally:
        if runner.is_alive():
            channel.request_abort()
            runner.join()


def _run_reserved_codex_cli(
    reservation: CodexProcessReservation,
    command: tuple[str, ...],
    **kwargs,
) -> CliRunOutcome:
    """Run one already-admitted CLI process through the bounded runner."""
    process_pool = get_codex_process_pool()

    def on_spawned(process_id: int) -> None:
        process_pool.bind(reservation, process_id)

    def on_spawn_failed() -> None:
        process_pool.abandon_unspawned(reservation)

    def on_reaped(process_id: int, _became_zombie: bool) -> None:
        process_pool.reap(reservation, process_id)

    try:
        outcome = run_cli_bounded(
            command,
            on_spawned=on_spawned,
            on_spawn_failed=on_spawn_failed,
            on_reaped=on_reaped,
            **kwargs,
        )
    except BaseException:
        process_pool.abandon_unspawned(reservation)
        raise
    if outcome.reason is CliRunReason.SPAWN_FAILED:
        process_pool.abandon_unspawned(reservation)
    return outcome


def _copy_codex_login_mirror(codex_home: Path) -> None:
    """Install the complete redacted mirror in one private Codex home.

    Both Codex routes need the CLI's full subscription-login shape. The
    host-side mirror has already redacted renewal credentials; this last copy
    still writes a blank refresh field so an unexpectedly unredacted source
    cannot give the child a renewable login.
    """
    source = Path(CODEX_CLI_AUTH_FILE)
    target = codex_home / "auth.json"
    try:
        if not source.is_file():
            raise _CodexLoginMirrorError()
        document = json.loads(source.read_text())
        if not isinstance(document, dict):
            raise _CodexLoginMirrorError()
        tokens = document.get("tokens")
        if not isinstance(tokens, dict):
            raise _CodexLoginMirrorError()
        access_token = tokens.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise _CodexLoginMirrorError()
        auth_mode = document.get("auth_mode")
        id_token = tokens.get("id_token")
        account_id = tokens.get("account_id")
        last_refresh = document.get("last_refresh")
        if not all(
            isinstance(value, str) and value
            for value in (
                auth_mode,
                id_token,
                account_id,
                last_refresh,
            )
        ):
            raise _CodexLoginMirrorError()
        redacted_refresh_token = access_token[:0]
        target.write_text(
            json.dumps(
                {
                    "auth_mode": auth_mode,
                    "OPENAI_API_KEY": None,
                    "last_refresh": last_refresh,
                    "tokens": {
                        "id_token": id_token,
                        "access_token": access_token,
                        "account_id": account_id,
                        "refresh_token": redacted_refresh_token,
                    },
                }
            )
        )
        target.chmod(0o600)
    except _CodexLoginMirrorError:
        raise
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise _CodexLoginMirrorError() from exc


def _build_codex_image_command() -> tuple[str, ...]:
    """Return the fixed command for the image-only Codex route."""
    return (
        CODEX_CLI_BINARY,
        "exec",
        "--json",
        "--sandbox",
        "read-only",
        *_CODEX_IMAGE_ISOLATION_ARGS,
        "-",
    )


def _build_codex_command(*, sandbox: str, model: str | None = None) -> tuple[str, ...]:
    """Build one isolated Codex command for the selected sandbox and model."""
    return (
        CODEX_CLI_BINARY,
        "exec",
        "--json",
        "--sandbox",
        sandbox,
        *_CODEX_CLI_ISOLATION_ARGS,
        *(("--model", model) if model is not None else ()),
        "-",
    )


def _raise_for_codex_image_outcome(outcome: CliRunOutcome) -> None:
    if _codex_cli_failure_reason(outcome.stderr) is SafeRouteReasonCode.CLI_AUTH_REJECTED:
        raise CodexImageLoginError()
    if outcome.reason in {
        CliRunReason.DEADLINE_BEFORE_SPAWN,
        CliRunReason.DEADLINE_WHILE_WRITING,
        CliRunReason.DEADLINE_WHILE_READING,
        CliRunReason.CLEANUP_OVERRAN,
    }:
        raise CodexImageTimeoutError()
    if not outcome.complete or outcome.returncode != 0:
        raise CodexImageCliError()


def _validate_codex_image_events(output: str, *, codex_home: Path) -> None:
    """Accept only image generation and its measured read-only bootstrap pair."""
    event_gate = _CodexImageEventGate(codex_home=codex_home)
    for line in output.splitlines():
        event_gate.accept(line.encode("utf-8"))
    event_gate.finish()


@dataclass
class _CodexImageEventGate:
    """Validate one image-run transcript, whether streamed or complete."""

    codex_home: Path
    saw_completed_turn: bool = False
    completed_error_item_message: str | None = None
    command_id: str | None = None
    saw_completed_command: bool = False

    def accept(self, line: bytes) -> None:
        """Accept one event while preserving the command-pair state."""
        try:
            event_type, event = _parse_codex_line(line)
            if event_type in _INFORMATIONAL_EVENT_TYPES:
                return
            if event_type == "turn.completed":
                if self.saw_completed_turn or not isinstance(event.get("usage"), dict):
                    raise CodexImageCliError()
                self.saw_completed_turn = True
                return
            if event_type in {"error", "turn.failed"}:
                raise CodexImageCliError()
            if event_type not in _ITEM_EVENT_TYPES:
                raise ImageToolBlockedError()
            item_type = _item_type(event)
            if event_type == _CODEX_ITEM_COMPLETED_EVENT and item_type == "error":
                self.completed_error_item_message = _completed_error_item_message(event)
                return
            if item_type == "command_execution":
                self.command_id, self.saw_completed_command = _validate_image_skill_command(
                    event_type,
                    event,
                    command_id=self.command_id,
                    saw_completed_command=self.saw_completed_command,
                    expected_command=_expected_image_skill_command(self.codex_home),
                )
                return
            if item_type in _BLOCKED_ITEM_TYPES:
                raise ImageToolBlockedError()
            if item_type in _INFORMATIONAL_ITEM_TYPES or item_type == "image_gen":
                return
            raise ImageToolBlockedError()
        except _CodexCliStreamFailure as exc:
            raise CodexImageCliError() from exc

    def finish(self) -> None:
        """Require a completed turn and its sole measured bootstrap command."""
        if self.saw_completed_turn:
            if self.command_id is not None and self.saw_completed_command:
                return
            raise ImageToolBlockedError()
        if (
            self.completed_error_item_message is not None
            and _codex_cli_failure_reason(self.completed_error_item_message)
            is SafeRouteReasonCode.CLI_AUTH_REJECTED
        ):
            raise CodexImageLoginError()
        raise CodexImageCliError()


def _expected_image_skill_command(codex_home: Path) -> str:
    skill_path = codex_home.resolve() / "skills" / ".system" / "imagegen" / "SKILL.md"
    return f"/bin/bash -lc \"sed -n '1,240p' {skill_path}\""


def _validate_image_skill_command(
    event_type: str,
    event: dict[str, object],
    *,
    command_id: str | None,
    saw_completed_command: bool,
    expected_command: str,
) -> tuple[str, bool]:
    item = _item(event)
    item_id = item.get("id")
    if not isinstance(item_id, str) or item.get("command") != expected_command:
        raise ImageToolBlockedError()
    if item.get("cwd") is not None:
        raise ImageToolBlockedError()
    if event_type == "item.started":
        if (
            command_id is not None
            or item.get("status") != "in_progress"
            or item.get("exit_code") is not None
        ):
            raise ImageToolBlockedError()
        return item_id, False
    if event_type == _CODEX_ITEM_COMPLETED_EVENT:
        if (
            command_id != item_id
            or saw_completed_command
            or item.get("status") != "completed"
            or item.get("exit_code") != 0
        ):
            raise ImageToolBlockedError()
        return command_id, True
    raise ImageToolBlockedError()


def _find_only_generated_png(codex_home: Path) -> Path:
    private_home = codex_home.resolve()
    root = private_home / "generated_images"
    if root.is_symlink():
        raise CodexImageArtifactError()
    candidates = [
        path
        for path in root.glob("**/*.png")
        if path.is_file() and path.resolve().is_relative_to(root)
    ]
    if not candidates:
        raise CodexImageNotCreatedError()
    if len(candidates) != 1:
        raise CodexImageArtifactError()
    return candidates[0]


def _normalize_generated_png(source: Path) -> bytes:
    try:
        if source.stat().st_size > 8 * 1024 * 1024:
            raise CodexImageArtifactError()
        with Image.open(source) as raw:
            if raw.width < 1 or raw.height < 1 or raw.width * raw.height > COVER_MAX_PIXELS:
                raise CodexImageArtifactError()
            raw.load()
            image = ImageOps.fit(raw.convert("RGB"), (1024, 1024), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="PNG")
        payload = output.getvalue()
        if not payload.startswith(COVER_PNG_MAGIC):
            raise CodexImageArtifactError()
        return payload
    except CodexImageArtifactError:
        raise
    except (OSError, ValueError) as exc:
        raise CodexImageArtifactError() from exc


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
    if thread_id is None:
        return (
            CODEX_CLI_BINARY,
            "exec",
            "--sandbox",
            "read-only",
            *common,
            "-",
        )
    return (
        CODEX_CLI_BINARY,
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
        return _run_reserved_codex_cli(
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


def _tool_transport_prompt(message: InitialTurn | ToolResultBatch) -> bytes:
    """Render one initial prompt or exactly one completed tool result."""
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


def _consume_codex_tool_event(
    event_type: str,
    event: dict[str, object],
    *,
    is_resume: bool,
    expected_thread_id: str | None,
    parser,
    state: _CodexToolRoundState,
    channel: CliLineChannel,
) -> str | None:
    """Apply one Codex event and return any safe assistant-text delta."""
    if state.saw_success:
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
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
    if event_type in _ITEM_EVENT_TYPES:
        return _consume_codex_item_event(event_type, event, parser, state, channel)
    if event_type == "turn.completed":
        _completed_turn(event)
        state.saw_success = True
        return None
    if event_type == "error":
        state.error_message = _top_level_error_message(event)
        channel.request_abort()
        return None
    if event_type == "turn.failed":
        state.error_message = _failed_turn_message(event)
        channel.request_abort()
        return None
    raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")


def _record_codex_thread_id(
    event: dict[str, object],
    *,
    is_resume: bool,
    expected_thread_id: str | None,
    state: _CodexToolRoundState,
) -> None:
    thread_id = _thread_started_id(event)
    if state.received_thread_id is not None or (is_resume and thread_id != expected_thread_id):
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
    state.received_thread_id = thread_id


def _consume_codex_item_event(
    event_type: str,
    event: dict[str, object],
    parser,
    state: _CodexToolRoundState,
    channel: CliLineChannel,
) -> str | None:
    item_type = _item_type(event)
    if item_type in _BLOCKED_ITEM_TYPES:
        raise _CodexCliStreamFailure("codex_cli_tool_call_blocked")
    if event_type == _CODEX_ITEM_COMPLETED_EVENT and item_type == "error":
        completed_error = _completed_error_item_message(event)
        if _is_code_mode_host_disabled_isolation_notice(completed_error):
            log.info("Codex CLI ignored its code-mode-host isolation notice")
            return None
        state.error_message = completed_error
        channel.request_abort()
        return None
    if item_type not in _INFORMATIONAL_ITEM_TYPES:
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
    if event_type == _CODEX_ITEM_COMPLETED_EVENT and item_type == "agent_message":
        return parser.feed(_completed_agent_message(event))
    return None


def _finish_codex_tool_round(
    outcome: CliRunOutcome,
    *,
    is_resume: bool,
    state: _CodexToolRoundState,
    parser,
    round_index: int,
    started_at: float,
) -> tuple[TransportResponse, str | None]:
    """Validate one completed Codex round and produce its terminal response."""
    from songmaker_cli.cowriter.text_tool_protocol import (
        FinalText as ParsedFinalText,
    )
    from songmaker_cli.cowriter.text_tool_protocol import (
        TextToolCall,
    )

    _raise_for_codex_outcome(outcome, state.saw_success, state.error_message, None)
    if not is_resume and state.received_thread_id is None:
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
    parsed = parser.finish()
    if isinstance(parsed, TextToolCall):
        call = ToolCall(str(uuid.uuid4()), parsed.name, parsed.arguments)
        _log_codex_tool_round(round_index, started_at, call.name)
        return ToolCallBatch((call,)), state.received_thread_id
    if isinstance(parsed, ParsedFinalText):
        _log_codex_tool_round(round_index, started_at, None)
        return FinalText(parsed.text), state.received_thread_id
    raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")


def _codex_cli_env(codex_home: Path) -> dict[str, str]:
    """Pass a scrubbed environment and only this turn's private Codex home."""
    environment = scrubbed_env()
    environment["CODEX_HOME"] = str(codex_home)
    return environment


def _thread_started_id(event: dict[str, object]) -> str:
    thread_id = event.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
    try:
        return str(uuid.UUID(thread_id))
    except ValueError as exc:
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error") from exc


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


def _completed_agent_message(event: dict[str, object]) -> str:
    item = _item(event)
    text = item.get("text")
    if not isinstance(text, str):
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
    return text


def _completed_error_item_message(event: dict[str, object]) -> str:
    message = _item(event).get("message")
    if not isinstance(message, str):
        raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
    return message


def _is_code_mode_host_disabled_isolation_notice(message: str) -> bool:
    """Recognize the one Codex notice caused by this adapter's isolation."""
    return message.startswith(_CODE_MODE_HOST_DISABLED_ISOLATION_NOTICE_PREFIX)


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
        normalize_route_failure(_codex_cli_failure_reason(error_message, outcome.stderr)),
    )


def _codex_cli_failure_reason(*messages: str | None) -> SafeRouteReasonCode:
    """Classify a Codex CLI failure without retaining its payload."""
    if any(_contains_auth_failure(message) for message in messages):
        return SafeRouteReasonCode.CLI_AUTH_REJECTED
    return SafeRouteReasonCode.CLI_PROTOCOL_ERROR


def _contains_auth_failure(value: str | None) -> bool:
    return value is not None and any(marker in value.lower() for marker in _AUTH_FAILURE_MARKERS)
