"""The command line starts the server and does nothing else."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from songmaker_cli.main import app


def _run(tokens: list[str]) -> None:
    """Cyclopts ends every invocation with a clean exit."""
    with pytest.raises(SystemExit) as finished:
        app(tokens)
    assert finished.value.code == 0


def test_the_command_line_offers_only_the_server() -> None:
    assert {name for name in app if not name.startswith("-")} == {"server"}


def test_the_help_lists_the_server_and_no_other_command(capsys) -> None:
    _run(["--help"])

    output = capsys.readouterr().out
    assert "server" in output
    for gone in ("login", "logout", "reset-password", "list-users", "albums", "generate"):
        assert gone not in output


def test_the_server_command_starts_the_server(tmp_path: Path) -> None:
    with patch("songmaker_cli.server.run_server") as run_server:
        _run(["server", "--port", "9001", "--root", str(tmp_path)])

    run_server.assert_called_once_with(
        project_root=tmp_path.resolve(), port=9001, open_browser=False,
    )
