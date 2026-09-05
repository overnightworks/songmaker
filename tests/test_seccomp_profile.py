"""Keep the web seccomp profile a narrowly derived Docker default."""

from __future__ import annotations

import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[1]
SECCOMP_DIRECTORY = REPOSITORY_ROOT / "scripts" / "seccomp"

_BUBBLEWRAP_SYSCALLS = [
    "unshare",
    "mount",
    "umount2",
    "pivot_root",
    "setns",
    "mount_setattr",
    "open_tree",
    "move_mount",
    "fsopen",
]


def _profile(name: str) -> dict[str, object]:
    return json.loads((SECCOMP_DIRECTORY / name).read_text())


def test_web_seccomp_profile_only_adds_the_bubblewrap_setup_extension() -> None:
    docker_default = _profile("moby-default.json")
    web_profile = _profile("songmaker-web.json")
    web_syscalls = web_profile["syscalls"]

    assert isinstance(web_syscalls, list)
    assert docker_default == {
        **web_profile,
        "syscalls": web_syscalls[:-2],
    }
    assert web_syscalls[-2:] == [
        {
            "names": _BUBBLEWRAP_SYSCALLS,
            "action": "SCMP_ACT_ALLOW",
        },
        {
            "names": ["clone"],
            "action": "SCMP_ACT_ALLOW",
        },
    ]
