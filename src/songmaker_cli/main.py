"""Songmaker CLI — starts the server and resets a password."""

from __future__ import annotations

import getpass
import logging
import sys
from pathlib import Path
from typing import Annotated, NoReturn, Optional

from cyclopts import App, CycloptsError, CycloptsPanel, Parameter
from cyclopts.core import _normalize_for_matching as _cyclopts_normalize_command_name

from songmaker_cli.errors import SongmakerError
from songmaker_cli.logging_config import configure_cli_logging

log = logging.getLogger(__name__)


_PASSWORD_COMMANDS = frozenset({"reset-password"})
_PASSWORD_COMMANDS_BY_NORMALIZED_NAME = {
    _cyclopts_normalize_command_name(name): name for name in _PASSWORD_COMMANDS
}


def _implicated_password_command(error: CycloptsError) -> str | None:
    """Return the password command this usage error concerns, if any.

    Cyclopts resolves command names case- and separator-insensitively (the
    same normalization as ``_cyclopts_normalize_command_name`` above), so a
    resolved ``command_chain`` entry is matched the same way rather than by
    exact string — otherwise an accepted alias like "LOGIN" or
    "reset_password" slips past. When no command resolved at all (a password
    typed before the command leaves ``command_chain`` empty), the full argv
    is the only place left to find the intended command, so every token is
    checked instead.
    """
    if error.command_chain:
        normalized = _cyclopts_normalize_command_name(error.command_chain[-1])
        return _PASSWORD_COMMANDS_BY_NORMALIZED_NAME.get(normalized)

    for token in error.root_input_tokens or ():
        normalized = _cyclopts_normalize_command_name(token)
        match = _PASSWORD_COMMANDS_BY_NORMALIZED_NAME.get(normalized)
        if match is not None:
            return match
    return None


def _format_usage_error(error: CycloptsError) -> str | CycloptsPanel:
    # Cyclopts error messages quote the offending token, and on a password
    # command that token is typically a password typed out of habit (also as
    # "--s3cret"); never print any of them back.
    command = _implicated_password_command(error)
    if command is not None:
        return (
            f"Error: usage is 'songmaker {command} USERNAME'; "
            "the password is only read at the prompt"
        )
    return CycloptsPanel(error)


app = App(
    name="songmaker",
    help="AI-powered song generation platform.",
    error_formatter=_format_usage_error,
)


@app.meta.default
def _launcher(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    verbose: Annotated[bool, Parameter(name=["-v", "--verbose"], help="Debug logging")] = False,
    quiet: Annotated[bool, Parameter(name=["-q", "--quiet"], help="Errors only")] = False,
) -> None:
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    configure_cli_logging(level)
    app(tokens)


# ── Server ──────────────────────────────────────────────────────────


@app.command
def server(
    port: Annotated[int, Parameter(help="Server port")] = 8080,
    root: Annotated[Optional[str], Parameter(help="Project root")] = None,
    open_browser: Annotated[
        bool, Parameter(name="--open", help="Open browser on start"),
    ] = False,
) -> None:
    """Start the songmaker web server."""
    from songmaker_cli.server import run_server

    project_root = Path(root).resolve() if root else None
    run_server(project_root=project_root, port=port, open_browser=open_browser)


# ── Auth (local DB commands) ────────────────────────────────────────


@app.command(name="reset-password")
def reset_password(
    username: Annotated[str, Parameter(help="Username to reset")],
) -> None:
    """Reset a user's password (asked twice) and end all its sessions (needs local DB access)."""
    from webauth.session_ending import end_user_sessions

    from songmaker_cli.api_models.auth import chosen_rule_refusal
    from songmaker_cli.app_context import build_password_hasher
    from songmaker_cli.auth_stores import DatabaseSessionRecordStore
    from songmaker_cli.db.engine import init_db, resolve_database_url
    from songmaker_cli.db.queries.auth import get_user_by_username, update_user
    from songmaker_cli.settings import get_settings

    password = _ask_password("Password: ")
    if _ask_password("Repeat password: ") != password:
        _exit_with_error("the passwords do not match")
    refusal = chosen_rule_refusal(password)
    if refusal is not None:
        _exit_with_error(refusal)

    factory = init_db(resolve_database_url())
    with factory() as session:
        user = get_user_by_username(session, username)
        if not user:
            _exit_with_error(f"user '{username}' not found")
        update_user(session, user.id, password_hash=build_password_hasher().hash(password))
        sessions = DatabaseSessionRecordStore(
            session, session_max_age_seconds=get_settings().session_max_age_seconds,
        )
        ended = end_user_sessions(sessions, user.id)
        session.commit()
        print(f"Password reset for '{username}' (role={user.role}); {_sessions_ended(ended)}")


def _ask_password(prompt: str) -> str:
    try:
        return getpass.getpass(prompt)
    except EOFError:
        _exit_with_error("no password given")


def _exit_with_error(message: str) -> NoReturn:
    print(f"Error: {message}")
    sys.exit(1)


def _sessions_ended(count: int) -> str:
    noun = "session" if count == 1 else "sessions"
    return f"{count} {noun} ended"


# ── Main ────────────────────────────────────────────────────────────


def main() -> None:
    try:
        app.meta()
    except SongmakerError as exc:
        log.exception("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
