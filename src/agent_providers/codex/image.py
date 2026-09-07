"""The Codex CLI's album-cover image route.

What counts as an acceptable image is the host's decision, so every bound
this route enforces arrives as an :class:`~agent_providers.images.ImagePolicy`.

Pillow is imported only where an image is actually produced, so every
container can import this module for its error names while only the ones
that install the ``image`` extra ever run a turn.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Final

from agent_providers.codex.pool import CodexProcessKind, get_codex_process_pool
from agent_providers.codex.protocol import (
    BLOCKED_ITEM_TYPES,
    CODEX_APPROVAL_POLICY_NEVER_CONFIG,
    CODEX_CLI_LINE_CHANNEL_CAPACITY,
    CODEX_CLI_TURN_OUTPUT_READ_LIMIT_BYTES,
    CODEX_EMPTY_MCP_SERVERS_CONFIG,
    CODEX_ITEM_COMPLETED_EVENT,
    INFORMATIONAL_EVENT_TYPES,
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
from agent_providers.errors import SafeRouteReasonCode
from agent_providers.images import ImagePolicy
from agent_providers.process import CliLineChannel, CliRunOutcome, CliRunReason
from agent_providers.sandbox.paths import (
    CODEX_HOME_DIRECTORY_NAME,
    CODEX_IMAGE_TURN_DIRECTORY_PREFIX,
)

_IMAGE_ENCODER_PACKAGE: Final = "PIL"
_IMAGE_ENCODER_MISSING_DETAIL: Final = (
    "This deployment cannot encode an image: install the 'image' extra."
)
_USAGE_LIMIT_MARKER: Final = "usage limit"
# Codex's own wording for the retry hint, e.g. "... try again at Sep 7th, 2026 8:45 PM."
_USAGE_LIMIT_RETRY_AT_PATTERN: Final = re.compile(r"try again at (?P<retry_at>.+?)\.?\s*$")

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
    CODEX_APPROVAL_POLICY_NEVER_CONFIG,
    "-c",
    CODEX_EMPTY_MCP_SERVERS_CONFIG,
    "-c",
    'web_search="disabled"',
)


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


class CodexImageEncoderUnavailableError(CodexImageError):
    """This deployment has no image encoder, so no turn can produce a cover."""


class CodexImageQuotaError(CodexImageError):
    """The Codex account hit its usage limit for this turn."""

    def __init__(self, message: str, *, retry_at: str | None) -> None:
        super().__init__(message)
        self.retry_at = retry_at


def codex_cover_image_capability_is_available() -> bool:
    """Whether this process has every dependency for a cover image turn."""
    config = current_config()
    code_mode_host = config.codex_code_mode_host_binary
    resources = config.codex_resources_directory
    return (
        shutil.which(config.codex_cli_binary) is not None
        and code_mode_host.is_file()
        and os.access(code_mode_host, os.X_OK)
        and resources.is_dir()
        and image_encoder_is_installed()
    )


def image_encoder_is_installed() -> bool:
    """Whether this deployment installed the optional image encoder.

    A turn that reaches the encoder has already been paid for, so this is
    asked before the capability is offered and again before a process is
    spawned, never only where the encoder is imported.
    """
    return importlib.util.find_spec(_IMAGE_ENCODER_PACKAGE) is not None


def generate_codex_cover_image(
    prompt: str,
    *,
    policy: ImagePolicy,
    deadline: float,
    abort_signal: threading.Event | None = None,
    model: str = "",
) -> bytes:
    """Run one isolated Codex image turn and return its normalized PNG.

    The image route deliberately owns neither credentials nor process control:
    its caller has already selected the Codex CLI route, and every process is
    spawned through ``run_cli_bounded``.  Its temporary ``CODEX_HOME`` is the
    only place where a generated artifact may be discovered.
    """
    if not image_encoder_is_installed():
        raise CodexImageEncoderUnavailableError(_IMAGE_ENCODER_MISSING_DETAIL)
    with tempfile.TemporaryDirectory(
        prefix=CODEX_IMAGE_TURN_DIRECTORY_PREFIX,
        dir=current_config().cli_working_directory_root,
    ) as directory:
        root = Path(directory)
        work_dir = root / "work"
        codex_home = root / CODEX_HOME_DIRECTORY_NAME
        root.chmod(0o700)
        work_dir.mkdir(mode=0o700)
        codex_home.mkdir(mode=0o700)
        try:
            copy_codex_login_mirror(codex_home)
        except CodexLoginMirrorError as exc:
            raise CodexImageLoginError() from exc
        outcome = _run_codex_image_cli(
            prompt=prompt,
            deadline=deadline,
            codex_home=codex_home,
            work_dir=work_dir,
            abort_signal=abort_signal,
            model=model,
        )
        _raise_for_codex_image_outcome(outcome)
        _validate_codex_image_events(
            outcome.stdout,
            codex_home=codex_home,
        )
        artifact = _find_only_generated_png(codex_home)
        return _normalize_generated_png(artifact, policy)


def _run_codex_image_cli(
    *,
    prompt: str,
    deadline: float,
    codex_home: Path,
    work_dir: Path,
    abort_signal: threading.Event | None = None,
    model: str = "",
) -> CliRunOutcome:
    """Reap the CLI promptly when its streamed events leave the image gate."""
    channel = CliLineChannel(CODEX_CLI_LINE_CHANNEL_CAPACITY)
    event_gate = _CodexImageEventGate(codex_home=codex_home)
    reservation = get_codex_process_pool().reserve(CodexProcessKind.IMAGE)

    def run() -> None:
        result = run_reserved_codex_cli(
            reservation,
            _build_codex_image_command(model),
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


def _build_codex_image_command(model: str) -> tuple[str, ...]:
    """Return the fixed command for the image-only Codex route."""
    return (
        current_config().codex_cli_binary,
        "exec",
        "--json",
        "--sandbox",
        "read-only",
        *_CODEX_IMAGE_ISOLATION_ARGS,
        *(("--model", model) if model else ()),
        "-",
    )


def _raise_for_codex_image_outcome(outcome: CliRunOutcome) -> None:
    if codex_cli_failure_reason(outcome.stderr) is SafeRouteReasonCode.CLI_AUTH_REJECTED:
        raise CodexImageLoginError()
    if outcome.reason in {
        CliRunReason.DEADLINE_BEFORE_SPAWN,
        CliRunReason.DEADLINE_WHILE_WRITING,
        CliRunReason.DEADLINE_WHILE_READING,
        CliRunReason.CLEANUP_OVERRAN,
    }:
        raise CodexImageTimeoutError()
    if outcome.complete and outcome.returncode == 0:
        return
    message = _codex_image_turn_failure_message(outcome.stdout)
    if message is None:
        raise CodexImageCliError()
    if codex_cli_failure_reason(message) is SafeRouteReasonCode.CLI_AUTH_REJECTED:
        raise CodexImageLoginError()
    if _USAGE_LIMIT_MARKER in message.lower():
        match = _USAGE_LIMIT_RETRY_AT_PATTERN.search(message)
        raise CodexImageQuotaError(
            message, retry_at=match.group("retry_at") if match else None,
        )
    raise CodexImageCliError(message)


def _codex_image_turn_failure_message(stdout: str) -> str | None:
    """Read the last turn-failure message the CLI reported on stdout, if any."""
    message: str | None = None
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event_type, event = parse_codex_line(line.encode("utf-8"))
            if event_type == "error":
                message = top_level_error_message(event)
            elif event_type == "turn.failed":
                message = failed_turn_message(event)
        except CodexCliStreamFailure:
            continue
    return message


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
            event_type, event = parse_codex_line(line)
            if event_type in INFORMATIONAL_EVENT_TYPES:
                return
            if event_type == "turn.completed":
                if self.saw_completed_turn or not isinstance(event.get("usage"), dict):
                    raise CodexImageCliError()
                self.saw_completed_turn = True
                return
            if event_type in {"error", "turn.failed"}:
                raise CodexImageCliError()
            if event_type not in ITEM_EVENT_TYPES:
                raise ImageToolBlockedError()
            item_type = event_item_type(event)
            if event_type == CODEX_ITEM_COMPLETED_EVENT and item_type == "error":
                self.completed_error_item_message = error_item_message(event)
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
            if item_type in BLOCKED_ITEM_TYPES:
                raise ImageToolBlockedError()
            if item_type in INFORMATIONAL_ITEM_TYPES or item_type == "image_gen":
                return
            raise ImageToolBlockedError()
        except CodexCliStreamFailure as exc:
            raise CodexImageCliError() from exc

    def finish(self) -> None:
        """Require a completed turn and its sole measured bootstrap command."""
        if self.saw_completed_turn:
            if self.command_id is not None and self.saw_completed_command:
                return
            raise ImageToolBlockedError()
        if (
            self.completed_error_item_message is not None
            and codex_cli_failure_reason(self.completed_error_item_message)
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
    item = event_item(event)
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
    if event_type == CODEX_ITEM_COMPLETED_EVENT:
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


def _normalize_generated_png(source: Path, policy: ImagePolicy) -> bytes:
    image_module, operations = _require_pillow()
    edge = (policy.output_edge_pixels, policy.output_edge_pixels)
    try:
        if source.stat().st_size > policy.maximum_source_bytes:
            raise CodexImageArtifactError()
        with image_module.open(source) as raw:
            if raw.width < 1 or raw.height < 1 or raw.width * raw.height > policy.maximum_pixels:
                raise CodexImageArtifactError()
            raw.load()
            image = operations.fit(
                raw.convert("RGB"), edge, image_module.Resampling.LANCZOS,
            )
        output = BytesIO()
        image.save(output, format=policy.output_format)
        payload = output.getvalue()
        if not payload.startswith(policy.output_signature):
            raise CodexImageArtifactError()
        return payload
    except CodexImageArtifactError:
        raise
    except (OSError, ValueError) as exc:
        raise CodexImageArtifactError() from exc


def _require_pillow():
    """Import Pillow only where an image is actually produced.

    Every container imports this module for its error names, but only the
    ones that install the ``image`` extra ever reach this line — a turn
    without it is refused before it spawns.
    """
    from PIL import Image, ImageOps

    return Image, ImageOps
