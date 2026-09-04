"""Codex subscription CLI transport for one tool-free co-writer turn."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from typing import Final

from PIL import Image, ImageOps, UnidentifiedImageError

from songmaker_cli.agent_cli import (
    CliLineChannel,
    CliRunOutcome,
    CliRunReason,
    run_cli_bounded,
)
from songmaker_cli.claude.provider import (
    AssistantTextEvent,
    FinalEvent,
    StreamEvent,
    _flatten_messages,
    _stdin_prompt,
)
from songmaker_cli.constants import (
    CODEX_CLI_AUTH_FILE,
    CODEX_CLI_BINARY,
    COVER_MAX_PIXELS,
    COVER_PNG_MAGIC,
    COWRITER_CLI_TIMEOUT_SECONDS,
)
from songmaker_cli.cowriter.errors import (
    ProviderUnavailableError,
    SafeRouteReasonCode,
    normalize_route_failure,
)

CODEX_CLI_LINE_CHANNEL_CAPACITY: Final = 64
CODEX_CLI_TURN_OUTPUT_READ_LIMIT_BYTES: Final = 4 * 1024 * 1024
_AUTH_FAILURE_MARKERS: Final = ("401", "unauthorized", "unauthenticated")
_BLOCKED_ITEM_TYPES: Final = frozenset({
    "collab_agent_tool_call", "command_execution", "file_change", "image_generation",
    "mcp_tool_call", "web_search",
})
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
    'approval_policy="never"',
    "-c",
    "mcp_servers={}",
)
_INFORMATIONAL_ITEM_TYPES: Final = frozenset({
    "agent_message", "reasoning", "todo_list",
})
_ITEM_EVENT_TYPES: Final = frozenset({
    "item.started", "item.updated", "item.completed",
})
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


class CodexImageTimeoutError(CodexImageError):
    """The bounded CLI call exceeded its image-generation deadline."""


class CodexImageCliError(CodexImageError):
    """The CLI ended without a verified successful image result."""


async def stream_codex_cli_turn(
    *, system: str, model: str, messages: list[dict[str, str]],
) -> AsyncIterator[StreamEvent]:
    """Yield Codex text events only after its subscription CLI accepts the turn."""
    prompt = _stdin_prompt(system, _flatten_messages("", messages)).encode()
    channel = CliLineChannel(CODEX_CLI_LINE_CHANNEL_CAPACITY)
    deadline = time.monotonic() + COWRITER_CLI_TIMEOUT_SECONDS
    turn_directory = tempfile.TemporaryDirectory(prefix="songmaker-codex-cli-")
    codex_home = Path(turn_directory.name) / "codex-home"
    try:
        codex_home.mkdir()
        _copy_codex_login_mirror(codex_home)
    except _CodexLoginMirrorError as exc:
        turn_directory.cleanup()
        raise ProviderUnavailableError(
            "codex",
            "cli",
            normalize_route_failure(SafeRouteReasonCode.CLI_AUTH_REJECTED),
        ) from exc
    runner = asyncio.create_task(asyncio.to_thread(
        run_cli_bounded,
        _build_codex_cli_command(model),
        stdin_payload=prompt,
        read="all",
        deadline=deadline,
        output_read_limit_bytes=CODEX_CLI_TURN_OUTPUT_READ_LIMIT_BYTES,
        stdout_line_channel=channel,
        cwd=turn_directory.name,
        extra_env={"CODEX_HOME": str(codex_home)},
    ))
    text_chunks: list[str] = []
    saw_success = False
    error_message: str | None = None
    completed_error_item_message: str | None = None
    try:
        while True:
            line_or_outcome = await asyncio.to_thread(channel.receive)
            if isinstance(line_or_outcome, CliRunOutcome):
                outcome = line_or_outcome
                break
            if saw_success:
                raise _CodexCliStreamFailure("codex_cli_stream_protocol_error")
            event_type, event = _parse_codex_line(line_or_outcome)
            if event_type in _INFORMATIONAL_EVENT_TYPES:
                continue
            if event_type in _ITEM_EVENT_TYPES:
                item_type = _item_type(event)
                if item_type in _BLOCKED_ITEM_TYPES:
                    raise _CodexCliStreamFailure("codex_cli_tool_call_blocked")
                if event_type == "item.completed" and item_type == "error":
                    completed_error_item_message = _completed_error_item_message(event)
                    _log_completed_error_item(completed_error_item_message)
                    continue
                if item_type not in _INFORMATIONAL_ITEM_TYPES:
                    raise _unsupported_stream_event(event_type, item_type)
                if event_type == "item.completed" and item_type == "agent_message":
                    text = _completed_agent_message(event)
                    text_chunks.append(text)
                    yield AssistantTextEvent(text=text)
                continue
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
            raise _unsupported_stream_event(event_type)
        await asyncio.shield(runner)
        _raise_for_codex_outcome(
            outcome,
            saw_success,
            error_message,
            completed_error_item_message,
        )
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


def generate_codex_cover_image(prompt: str, *, deadline: float) -> bytes:
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
        work_dir.mkdir()
        codex_home.mkdir()
        try:
            _copy_codex_login_mirror(codex_home)
        except _CodexLoginMirrorError as exc:
            raise CodexImageLoginError() from exc
        outcome = run_cli_bounded(
            _build_codex_image_command(),
            stdin_payload=prompt.encode("utf-8"),
            read="all",
            deadline=deadline,
            output_read_limit_bytes=CODEX_CLI_TURN_OUTPUT_READ_LIMIT_BYTES,
            cwd=str(work_dir),
            extra_env={"CODEX_HOME": str(codex_home)},
        )
        _raise_for_codex_image_outcome(outcome)
        _validate_codex_image_events(outcome.stdout)
        artifact = _find_only_generated_png(codex_home)
        return _normalize_generated_png(artifact)


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
        if not all(isinstance(value, str) and value for value in (
            auth_mode, id_token, account_id, last_refresh,
        )):
            raise _CodexLoginMirrorError()
        target.write_text(json.dumps({
            "auth_mode": auth_mode,
            "OPENAI_API_KEY": None,
            "last_refresh": last_refresh,
            "tokens": {
                "id_token": id_token,
                "access_token": access_token,
                "account_id": account_id,
                "refresh_token": "",
            },
        }))
        target.chmod(0o600)
    except _CodexLoginMirrorError:
        raise
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise _CodexLoginMirrorError() from exc


def _build_codex_image_command() -> tuple[str, ...]:
    """Return the fixed command for the image-only Codex route."""
    return _build_codex_command(sandbox="workspace-write")


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


def _validate_codex_image_events(output: str) -> None:
    saw_completed_turn = False
    completed_error_item_message: str | None = None
    try:
        for line in output.splitlines():
            event_type, event = _parse_codex_line(line.encode("utf-8"))
            if event_type in _INFORMATIONAL_EVENT_TYPES:
                continue
            if event_type == "turn.completed":
                if saw_completed_turn or not isinstance(event.get("usage"), dict):
                    raise CodexImageCliError()
                saw_completed_turn = True
                continue
            if event_type in {"error", "turn.failed"}:
                raise CodexImageCliError()
            if event_type in _ITEM_EVENT_TYPES:
                item_type = _item_type(event)
                if event_type == "item.completed" and item_type == "error":
                    completed_error_item_message = _completed_error_item_message(event)
                    continue
                if item_type in _BLOCKED_ITEM_TYPES:
                    raise ImageToolBlockedError()
                if item_type in _INFORMATIONAL_ITEM_TYPES or item_type == "image_gen":
                    continue
                raise CodexImageCliError()
            raise CodexImageCliError()
    except _CodexCliStreamFailure as exc:
        raise CodexImageCliError() from exc
    if saw_completed_turn:
        return
    if completed_error_item_message is not None:
        if _codex_cli_failure_reason(
            completed_error_item_message,
        ) is SafeRouteReasonCode.CLI_AUTH_REJECTED:
            raise CodexImageLoginError()
        raise CodexImageCliError()
    raise CodexImageCliError()


def _find_only_generated_png(codex_home: Path) -> Path:
    root = codex_home.resolve()
    candidates = [
        path for path in codex_home.glob("**/*.png")
        if path.is_file() and path.resolve().is_relative_to(root)
    ]
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
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise CodexImageArtifactError() from exc


def _build_codex_cli_command(model: str) -> tuple[str, ...]:
    """Return the fixed, tool-free Codex command for a single streamed turn."""
    return _build_codex_command(sandbox="read-only", model=model)


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


def _log_completed_error_item(message: str) -> None:
    log.warning(
        "Codex CLI error item (message_class=%s)",
        _error_message_class(message),
    )


def _error_message_class(message: str) -> str:
    words: list[str] = []
    for word in message.split():
        if not word.isalpha() or len(word) > 24:
            break
        words.append(word.lower())
        if len(words) == 4:
            break
    return "_".join(words) or "unclassified"


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


def _unsupported_stream_event(
    event_type: str, item_type: str | None = None,
) -> _CodexCliStreamFailure:
    if item_type is None:
        log.warning("Codex CLI stream protocol error (event_type=%s)", event_type)
    else:
        log.warning(
            "Codex CLI stream protocol error (event_type=%s, item_type=%s)",
            event_type,
            item_type,
        )
    return _CodexCliStreamFailure("codex_cli_stream_protocol_error")


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
    if not saw_success:
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
