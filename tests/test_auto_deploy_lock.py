"""The deploy lock is held by the tick alone, never by a git child it started."""

from __future__ import annotations

import contextlib
import os
import shlex
import signal
from pathlib import Path

from auto_deploy_harness import Checkout
from auto_deploy_support import git, write_executable

DETACHED_CHILD_SECONDS = 60


def test_a_detached_child_left_by_a_fetch_does_not_make_the_next_tick_skip(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    # What git's detached maintenance does: a session of its own that keeps
    # every fd it inherited. Each child is bounded and ended below.
    child_pids = tmp_path / "detached-child-pids"
    upload_pack = tmp_path / "detaching-upload-pack"
    write_executable(
        upload_pack,
        "#!/bin/bash\n"
        f"setsid sleep {DETACHED_CHILD_SECONDS} </dev/null >/dev/null 2>&1 &\n"
        f"echo $! >>{shlex.quote(str(child_pids))}\n"
        'exec /usr/bin/git-upload-pack "$@"\n',
    )
    git(checkout.root, "config", "remote.origin.uploadpack", str(upload_pack))
    try:
        assert checkout.tick().returncode == 0
        first_child_pid = int(child_pids.read_text().split()[0])

        assert checkout.tick().returncode == 0

        os.kill(first_child_pid, 0)
        assert "another run is already in flight" not in checkout.journal
    finally:
        if child_pids.exists():
            for child_pid in map(int, child_pids.read_text().split()):
                with contextlib.suppress(ProcessLookupError):
                    os.kill(child_pid, signal.SIGKILL)
