"""Recording fakes and checkout helpers for the shell installers' tests.

The fakes stand in for ``sudo``, ``systemctl``, ``getent`` and friends on PATH; every one of
them only records, as the comment below sets out.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

# The fakes below RECORD. They do not run anything.
#
# Earlier versions of these fakes exec'd what they were asked to run, behind a
# growing wall of allowlists, and one of them rebooted the operator's machine.
# Every round of hardening found the next way through — `install -tDIR SRC`,
# `install -d OUT IN`, `--strip-program=/usr/bin/id`, a glob in an ExecStart
# that expands after the check, a shebang in an otherwise contained script.
# That is not a series of bugs; a shell stand-in that executes cannot be
# contained, because containing it means reimplementing the argument grammar
# of every program it might start.
#
# So there is one rule, and it is structural rather than enumerated: no branch
# of either fake starts a program. Everything below is a bash builtin. The one
# effect they still have — `install` putting a file where the installer put it
# — is a builtin read and a redirect, and only into a path that is textually
# under the sandbox, contains no `..`, and is not itself a symlink.
#
# `grep -nE 'exec|[$][(]|`' over both bodies must come back empty.

RECORDER = """
refuse() { printf 'fake %s: refusing %s\n' "$FAKE_NAME" "$*" >&2; exit 97; }

[ -n "${SANDBOX_ROOT:-}" ] || refuse "SANDBOX_ROOT is not set"
[ -n "${RECORDING:-}" ] || refuse "RECORDING is not set"

# A textual prefix and no dot-dot. Deliberately NOT a resolution: resolving meant
# running readlink, and a resolved answer was still stale by the time anything
# used it. Nothing here follows a path far enough for that to matter.
inside() {
    case "${1:-}" in
        *..*) return 1 ;;
        "$SANDBOX_ROOT"/*) return 0 ;;
    esac
    return 1
}

# A redirect follows a symlink, so a textual prefix alone would let a link
# inside the sandbox carry a write out of it. Only the target itself is judged,
# never its parent chain — that would be resolution again, and the sandbox is a
# freshly made tmp_path in which only our own test or installer code could put
# a link at all.
writable_target() {
    inside "${1:-}" || return 1
    [ ! -L "${1:-}" ] || return 1
    return 0
}

writable_target "$RECORDING" \
    || refuse "recording file outside the sandbox or through a symlink"

record() { printf '%s\n' "$*" >> "$RECORDING"; }
"""

# One state table for both fakes, so `sudo systemctl enable X` and a later
# `systemctl is-enabled X` cannot disagree. The test seeds it to describe a
# machine — a failed service, a stopped timer — instead of a fake pretending
# to run one.
SYSTEMCTL_STATE = """
STATE_FILE="$SANDBOX_ROOT/systemctl-state"

writable_target "$STATE_FILE" || refuse "state file is a symlink"

state_add() { printf '%s\n' "$1" >> "$STATE_FILE"; }

state_has() {
    local wanted="$1" line
    while IFS= read -r line || [ -n "$line" ]; do
        [ "$line" = "$wanted" ] && return 0
    done < "$STATE_FILE" 2> /dev/null
    return 1
}

valid_unit_name() {
    case "${1:-}" in
        "") return 1 ;;
        *[!A-Za-z0-9@_.-]*) return 1 ;;
        *..*) return 1 ;;
    esac
    return 0
}

# Sets a variable rather than echoing, so no branch of these fakes needs a
# command substitution at all — the containment claim is then a grep, not an
# argument about which substitutions fork.
UNIT_NAME=""
unit_of() {
    shift
    UNIT_NAME=""
    for one in "$@"; do
        case "$one" in
            --*) ;;
            *) UNIT_NAME="$one"; return ;;
        esac
    done
}

# systemd's verbs, answered from the table. A start records the request and
# changes the table; it does NOT run the unit's ExecStart. That the mirror
# script really creates its directories is pinned directly against the script
# in tests/scripts/test_mirror_agent_cli_credentials.py, where no fake is involved.
systemctl_dispatch() {
    local operation="${1:-}" unit
    case "$operation" in
        daemon-reload) return 0 ;;
        enable|start|is-enabled|is-active|is-failed|list-unit-files) ;;
        *) refuse "unmodelled command '$operation'" ;;
    esac

    unit_of "$@"
    unit="$UNIT_NAME"
    valid_unit_name "$unit" || refuse "unit name '$unit' is not a plain unit name"

    case "$operation" in
        enable)
            state_add "enabled $unit"
            case "$*" in *--now*) state_add "active $unit" ;; esac
            return 0 ;;
        start)
            state_add "active $unit"
            return 0 ;;
        is-enabled) state_has "enabled $unit"; return $? ;;
        is-active) state_has "active $unit"; return $? ;;
        is-failed) state_has "failed $unit"; return $? ;;
        list-unit-files)
            if [ -f "$SONGMAKER_UNIT_DIR/$unit" ]; then
                printf '%s enabled enabled\n' "$unit"
            fi
            return 0 ;;
    esac
}
"""

FAKE_SYSTEMCTL = (
    '#!/bin/bash\nFAKE_NAME=systemctl\n' + RECORDER + SYSTEMCTL_STATE + """
inside "${SONGMAKER_UNIT_DIR:-}" || refuse "unit dir outside the sandbox"
record "systemctl $*"
systemctl_dispatch "$@"
exit $?
"""
)

# The installer runs exactly three shapes through sudo:
#   sudo install -m MODE SOURCE TARGET
#   sudo systemctl ...
#   sudo -u OPERATOR <preflight script> ...
# The first is matched EXACTLY, argument count included, rather than by
# parsing GNU install's option grammar — every attempt at that grammar left
# another way to name a second destination. The third is recorded and
# answered according to FAKE_SUDO_U_EXIT without running anything; what the
# preflight would have reported is asserted directly in the tests that drive it.
FAKE_SUDO = (
    '#!/bin/bash\nFAKE_NAME=sudo\n' + RECORDER + SYSTEMCTL_STATE + """
record "sudo $*"

if [ "${1:-}" = "-u" ]; then
    [ $# -ge 3 ] || refuse "-u without both a user and a command"
    shift 2
    inside "${1:-}" || refuse "-u command '${1:-}' outside the sandbox"
    if [ -n "${FAKE_SUDO_U_OUTPUT:-}" ]; then
        printf '%s\n' "$FAKE_SUDO_U_OUTPUT"
    fi
    exit "${FAKE_SUDO_U_EXIT:-0}"
fi

case "${1:-}" in
    install)
        [ $# -eq 5 ] \
            || refuse "install with an argument count the installer never uses;" \
                      "it uses: install -m MODE SOURCE TARGET"
        [ "$2" = "-m" ] || refuse "install without -m as its first option"
        inside "$4" || refuse "install reading '$4' outside the sandbox"
        writable_target "$5" \
            || refuse "install writing '$5' outside the sandbox or through a symlink"
        mapfile -t -d '' whole < "$4"
        printf '%s' "${whole[0]-}" > "$5"
        exit 0 ;;
    systemctl)
        inside "${SONGMAKER_UNIT_DIR:-}" || refuse "unit dir outside the sandbox"
        shift
        systemctl_dispatch "$@"
        exit $? ;;
esac

refuse "command '${1:-}' — this fake records install, systemctl and -u only"
"""
)

FAKE_GETENT = """#!/bin/bash
if [ "$1" = "passwd" ]; then
    printf '%s:x:1000:1000::%s:/bin/bash\n' "$2" "$FAKE_OPERATOR_HOME"
    exit 0
fi
exit 2
"""


# The account the installer is told it was sudo'd from. Fixed, because
# `${SUDO_USER:-$(id -un)}` would otherwise resolve to whoever runs pytest and
# put that name into the assertions.
DEFAULT_SUDO_USER = "operator"

# What a subprocess started by this test is allowed to inherit. Everything
# else is dropped, not merged: BASH_ENV runs a file before any fake's first
# line, an exported shell function named `sudo` beats PATH, LD_PRELOAD acts
# before the program starts, and PYTHONPATH reaches the mirror script. None of
# those need to be enumerated as attacks if the environment is built rather
# than inherited.
INHERITED_ENVIRONMENT = ("LANG", "LC_ALL", "TERM")


def make_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def linked_worktree_of(checkout: Path, tmp_path: Path) -> Path:
    identity = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e",
    }
    subprocess.run(["git", "add", "-A"], cwd=checkout, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "base"],
        cwd=checkout, check=True, env=identity,
    )
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "worktree", "add", "-q", "--detach", str(linked)],
        cwd=checkout, check=True,
    )
    return linked
