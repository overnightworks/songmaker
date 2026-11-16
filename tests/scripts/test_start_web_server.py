"""The web container's start script leaves the log to the server."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from support.repository_root import REPOSITORY_ROOT

START_SCRIPT = REPOSITORY_ROOT / "docker" / "scripts" / "start_web_server.sh"


def test_web_entrypoint_script_writes_no_line_of_its_own(tmp_path: Path) -> None:
    """The container's log holds only the server's JSON lines, so the script before it is silent."""
    fake_uv = tmp_path / "uv"
    fake_uv.write_text("#!/bin/sh\nexit 0\n")
    fake_uv.chmod(0o755)

    completed = subprocess.run(
        ["bash", str(START_SCRIPT)],
        env={"PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=True,
    )

    assert (completed.stdout, completed.stderr) == ("", "")
