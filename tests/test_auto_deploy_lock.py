"""The deploy lock is held by the tick alone, never by a git child it started."""

from __future__ import annotations

import contextlib
import os
import shlex
import signal
import time
from pathlib import Path

from auto_deploy_harness import Checkout
from auto_deploy_support import git, write_executable

DETACHED_CHILD_SECONDS = 60
READINESS_TIMEOUT_SECONDS = 10
LOCK_FILE_NAME = "songmaker-autodeploy.lock"


def _process_state(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return None
    # The state letter follows the parenthesised command name.
    return stat.rpartition(")")[2].split()[0]


def _holds_lock_file_open(pid: int) -> bool:
    for descriptor in Path(f"/proc/{pid}/fd").iterdir():
        with contextlib.suppress(OSError):
            if Path(os.readlink(descriptor)).name == LOCK_FILE_NAME:
                return True
    return False


def _is_live(pid: int) -> bool:
    return _process_state(pid) not in (None, "Z", "X")


def _wait_until_gone(pid: int) -> None:
    deadline = time.monotonic() + READINESS_TIMEOUT_SECONDS
    while _is_live(pid) and time.monotonic() < deadline:
        time.sleep(0.05)


def test_a_detached_child_left_by_a_fetch_does_not_make_the_next_tick_skip(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    # What git's detached maintenance does: a session of its own that keeps
    # every fd it inherited. The child announces itself only once it runs in
    # its new session, and the fetch is served only after that, so the tick
    # cannot end the child's process group before it has detached.
    ready_directory = tmp_path / "detached-children"
    ready_directory.mkdir()
    upload_pack = tmp_path / "detaching-upload-pack"
    write_executable(
        upload_pack,
        "#!/bin/bash\n"
        f"ready={shlex.quote(str(ready_directory))}/$$\n"
        "setsid sh -c 'echo $$ >\"$1.tmp\" && mv \"$1.tmp\" \"$1\";"
        f" exec sleep {DETACHED_CHILD_SECONDS}'"
        ' sh "$ready" </dev/null >/dev/null 2>&1 &\n'
        f"for _ in $(seq {READINESS_TIMEOUT_SECONDS * 20}); do\n"
        '    [ -e "$ready" ] && exec /usr/bin/git-upload-pack "$@"\n'
        "    sleep 0.05\n"
        "done\n"
        'echo "detached child never became ready" >&2\n'
        "exit 1\n",
    )
    git(checkout.root, "config", "remote.origin.uploadpack", str(upload_pack))
    try:
        assert checkout.tick().returncode == 0
        ready_files = sorted(ready_directory.glob("[0-9]*"))
        assert ready_files, "the fetch never ran the detaching upload-pack"
        child_pid = int(ready_files[0].read_text())

        assert checkout.tick().returncode == 0

        assert _is_live(child_pid)
        assert not _holds_lock_file_open(child_pid)
        assert "another run is already in flight" not in checkout.journal
    finally:
        for ready_file in ready_directory.glob("[0-9]*"):
            pid = int(ready_file.read_text())
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
            _wait_until_gone(pid)
