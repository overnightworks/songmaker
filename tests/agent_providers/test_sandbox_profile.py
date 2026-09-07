"""The sandbox profiles the provider layer owns stay bound to its code.

Two deployment files carry the confinement the agent CLIs run under: the web
seccomp profile that permits Bubblewrap's namespace setup, and the AppArmor
profile that permits exactly the private Codex-home mounts the library binds.
Both are checked here against the values in ``agent_providers`` — a prefix or a
syscall that drifts from the code is a mount or a namespace the sandbox would
silently refuse. The files live under ``scripts/`` today; S1 repoints these
tests at the vendored deployment path after the extraction (issue #825).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from agent_providers.sandbox.paths import (
    CODEX_HOME_DIRECTORY_NAME,
    CODEX_IMAGE_TURN_DIRECTORY_PREFIX,
    CODEX_SANDBOX_PROOF_DIRECTORY,
    CODEX_TOOL_TURN_DIRECTORY_PREFIX,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
SECCOMP_DIRECTORY = REPOSITORY_ROOT / "scripts" / "seccomp"
APPARMOR_PROFILE_PATH = REPOSITORY_ROOT / "scripts" / "apparmor" / "songmaker-web"

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


_CODEX_HOME_MOUNT = re.compile(
    r"/tmp/(\{[^}]+\}|[A-Za-z0-9][A-Za-z0-9.*-]*)/" + re.escape(CODEX_HOME_DIRECTORY_NAME)
)


def _profile_codex_home_prefix_sets(profile: str) -> list[set[str]]:
    """Every prefix set the AppArmor profile names before a ``codex-home``.

    A single mount rule names one directory; the remount and tmpfs rules name
    all of them at once as a brace list. Both spellings are returned as sets,
    because a prefix dropped from either one is a mount the sandbox refuses.
    """
    return [
        {member.rstrip("*") for member in match.strip("{}").split(",")}
        for match in _CODEX_HOME_MOUNT.findall(profile)
    ]


def test_the_apparmor_profile_allows_exactly_the_codex_home_prefixes_in_use() -> None:
    """A prefix renamed without the profile is a silently blocked mount.

    Bubblewrap binds each private Codex home from a directory named by one of
    these prefixes, and only the mounts the profile lists are permitted, so
    every rule naming them has to agree with the code. The names live in
    ``agent_providers.sandbox.paths``; this holds the profile — the only file
    that permits those mounts — to that one owner (issue #876).
    """
    in_use = {
        CODEX_IMAGE_TURN_DIRECTORY_PREFIX,
        CODEX_TOOL_TURN_DIRECTORY_PREFIX,
        CODEX_SANDBOX_PROOF_DIRECTORY,
    }
    prefix_sets = _profile_codex_home_prefix_sets(APPARMOR_PROFILE_PATH.read_text())

    assert prefix_sets, "the profile names no codex-home mount at all"
    assert set().union(*prefix_sets) == in_use
    single_rules = [prefixes for prefixes in prefix_sets if len(prefixes) == 1]
    assert set().union(*single_rules) == in_use
    assert [prefixes for prefixes in prefix_sets if len(prefixes) > 1] == [in_use, in_use]
