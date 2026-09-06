"""The Codex CLI's shared plumbing: its isolation, its login, its events.

Both Codex routes — the co-writer tool transport and the album-cover image
turn — drive the same binary: they install the same redacted login into a
private home, spawn through the same admission-bound runner, and read the
same JSON event grammar. That common ground lives here so neither route
owns the other's internals.

Self-contained by design: no application import, so the package can be
released on its own (issue #825).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from agent_providers.codex.pool import CodexProcessReservation, get_codex_process_pool
from agent_providers.config import current_config
from agent_providers.errors import SafeRouteReasonCode
from agent_providers.process import CliRunOutcome, CliRunReason, run_cli_bounded

CODEX_CLI_LINE_CHANNEL_CAPACITY: Final = 64
CODEX_CLI_TURN_OUTPUT_READ_LIMIT_BYTES: Final = 4 * 1024 * 1024

_AUTH_FAILURE_MARKERS: Final = ("401", "unauthorized", "unauthenticated")

CODEX_APPROVAL_POLICY_NEVER_CONFIG: Final = 'approval_policy="never"'
CODEX_EMPTY_MCP_SERVERS_CONFIG: Final = "mcp_servers={}"
CODEX_ITEM_COMPLETED_EVENT: Final = "item.completed"
BLOCKED_ITEM_TYPES: Final = frozenset(
    {
        "collab_agent_tool_call",
        "command_execution",
        "file_change",
        "image_generation",
        "mcp_tool_call",
        "web_search",
    }
)
INFORMATIONAL_ITEM_TYPES: Final = frozenset(
    {
        "agent_message",
        "reasoning",
        "todo_list",
    }
)
ITEM_EVENT_TYPES: Final = frozenset(
    {
        "item.started",
        "item.updated",
        CODEX_ITEM_COMPLETED_EVENT,
    }
)
INFORMATIONAL_EVENT_TYPES: Final = frozenset({"thread.started", "turn.started"})


class CodexCliStreamFailure(Exception):
    """The streamed protocol named a terminal adapter failure."""

    def __init__(self, code: str) -> None:
        self.code = code



class CodexLoginMirrorError(Exception):
    """The redacted Codex login mirror cannot start an isolated CLI."""


def run_reserved_codex_cli(
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


def copy_codex_login_mirror(codex_home: Path) -> None:
    """Install the complete redacted mirror in one private Codex home.

    Both Codex routes need the CLI's full subscription-login shape. The
    host-side mirror has already redacted renewal credentials; this last copy
    still writes a blank refresh field so an unexpectedly unredacted source
    cannot give the child a renewable login.
    """
    source = current_config().codex_cli_auth_file
    target = codex_home / "auth.json"
    try:
        if not source.is_file():
            raise CodexLoginMirrorError()
        document = json.loads(source.read_text())
        if not isinstance(document, dict):
            raise CodexLoginMirrorError()
        tokens = document.get("tokens")
        if not isinstance(tokens, dict):
            raise CodexLoginMirrorError()
        access_token = tokens.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise CodexLoginMirrorError()
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
            raise CodexLoginMirrorError()
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
    except CodexLoginMirrorError:
        raise
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise CodexLoginMirrorError() from exc


def parse_codex_line(line: bytes) -> tuple[str, dict[str, object]]:
    try:
        event = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error") from exc
    if not isinstance(event, dict):
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error")
    event_type = event.get("type")
    if not isinstance(event_type, str):
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error")
    return event_type, event


def error_item_message(event: dict[str, object]) -> str:
    message = event_item(event).get("message")
    if not isinstance(message, str):
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error")
    return message


def event_item_type(event: dict[str, object]) -> str:
    item_type = event_item(event).get("type")
    if not isinstance(item_type, str):
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error")
    return item_type



def event_item(event: dict[str, object]) -> dict[str, object]:
    item = event.get("item")
    if not isinstance(item, dict):
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error")
    return item


def top_level_error_message(event: dict[str, object]) -> str:
    message = event.get("message")
    if not isinstance(message, str):
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error")
    return message



def failed_turn_message(event: dict[str, object]) -> str:
    error = event.get("error")
    if not isinstance(error, dict):
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error")
    message = error.get("message")
    if not isinstance(message, str):
        raise CodexCliStreamFailure("codex_cli_stream_protocol_error")
    return message


def codex_cli_failure_reason(*messages: str | None) -> SafeRouteReasonCode:
    """Classify a Codex CLI failure without retaining its payload."""
    if any(_contains_auth_failure(message) for message in messages):
        return SafeRouteReasonCode.CLI_AUTH_REJECTED
    return SafeRouteReasonCode.CLI_PROTOCOL_ERROR



def _contains_auth_failure(value: str | None) -> bool:
    return value is not None and any(marker in value.lower() for marker in _AUTH_FAILURE_MARKERS)
