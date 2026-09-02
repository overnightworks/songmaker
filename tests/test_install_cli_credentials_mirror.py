"""The mirror installer, driven as a real subprocess.

Two crashes shipped in this script because nothing ever ran it: `bash -n`
sees neither an unset variable at runtime nor a missing parent directory.
So this drives the real file, from a throwaway checkout, with `sudo`,
`systemctl` and `getent` replaced by fakes on PATH — no real units, no root,
nothing outside the temporary directories.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "scripts" / "install-cli-credentials-mirror.sh"

COPIED_SCRIPTS = (
    "install-cli-credentials-mirror.sh",
    "mirror_agent_cli_credentials.py",
    "check_agent_cli_mounts.sh",
    "agent-cli-paths.sh",
    "alert.sh",
    "songmaker-cli-credentials-mirror.service",
    "songmaker-cli-credentials-mirror.path",
    "songmaker-cli-credentials-mirror.timer",
    "songmaker-alert@.service",
)

# `sudo install ...` and `sudo -u USER CMD ...` are the only two shapes the
# installer uses; both run without privilege here.
#
# It refuses any absolute path outside the sandbox instead of running it. A
# fake that quietly did as it was told would, the moment the installer's early
# guards regressed, hand a test run the real /etc/systemd/system — and on a
# root test run it would write there. A fake stands in for a dangerous thing;
# it must be the *safe* half of it, not the compliant half.
# Refuses anything whose *resolved* location is outside the sandbox, then
# execs. Textual "does it start with /" was not enough: a relative path, a
# `$SANDBOX_ROOT/../../etc/...`, or a path through a symlinked directory all
# reached the real `install`. A fake stands in for a dangerous thing; it has to
# be the safe half of it, not the compliant half.
CONTAINMENT = """
inside_sandbox() {
    local resolved
    [ -n "${1:-}" ] || return 1
    # An ABSOLUTE path only. This is the trap that rebooted the operator's
    # machine: `readlink -m` happily resolves a bare name like `reboot` — or an
    # ExecStart of `touch` — against the current directory, which is inside the
    # sandbox, so the check said "contained" and the command then ran through
    # PATH as the real binary. A relative path makes no containment statement
    # at all, so it is refused rather than resolved.
    case "$1" in
        /*) ;;
        *) return 1 ;;
    esac
    resolved="$(readlink -m -- "$1" 2>/dev/null)" || return 1
    case "$resolved/" in
        "$SANDBOX_REAL"/*) return 0 ;;
    esac
    return 1
}

refuse() {
    echo "fake $FAKE_NAME: refusing $*" >&2
    exit 97
}

# Without the harness there is no sandbox to be inside of, and every check
# below would be comparing against an empty prefix. Refuse rather than guess.
[ -n "${SANDBOX_REAL:-}" ] || refuse "SANDBOX_REAL is not set"
[ -n "${SANDBOX_ROOT:-}" ] || refuse "SANDBOX_ROOT is not set"
"""

# An ALLOWLIST of the two command shapes the installer uses, and NOTHING else
# runs. This fake once rebooted the operator's machine: it scanned the
# arguments for things that looked like paths, `reboot` looked like none, and
# the command reached the real binary. The rewrite that followed was no better
# — its default branch resolved the bare name `reboot` against the sandbox
# working directory, decided it was contained, and exec'd it anyway.
#
# Hence the shape below: every permitted form ends in its own `exec`, and
# falling out of the case statement is a refusal. There is no shared exec at
# the bottom that a future branch could reach by forgetting something.
FAKE_SUDO = '#!/bin/bash\nFAKE_NAME=sudo\n' + CONTAINMENT + """
# The installer uses `sudo -u USER CMD ...` for the preflight and plain
# `sudo CMD ...` for the rest. The command after -u still has to be allowed.
dropped_privilege=0
if [ "${1:-}" = "-u" ]; then
    [ $# -ge 3 ] || refuse "-u without both a user and a command"
    dropped_privilege=1
    shift 2
fi

command_name="${1:-}"
[ -n "$command_name" ] || refuse "sudo with no command"
shift

case "$command_name" in
    install)
        # Parsed from a COPY: consuming the real arguments would leave nothing
        # to exec, and the destination can hide in an option value —
        # `--target-directory=/etc/systemd/system` is not path-shaped as an
        # argument, but it is exactly where the file would land.
        destination=""
        directory_option=""
        arguments=("$@")
        index=0
        while [ "$index" -lt "${#arguments[@]}" ]; do
            case "${arguments[$index]}" in
                --target-directory=*)
                    directory_option="${arguments[$index]#--target-directory=}" ;;
                -t|--target-directory)
                    index=$((index + 1))
                    directory_option="${arguments[$index]:-}" ;;
                -m) index=$((index + 1)) ;;
                -*) ;;
                *) destination="${arguments[$index]}" ;;
            esac
            index=$((index + 1))
        done
        # With -t or --target-directory, THAT is where the file lands and every
        # positional argument is a source. Letting the last positional win
        # meant checking a source inside the sandbox while the real
        # destination sat in /etc.
        [ -z "$directory_option" ] || destination="$directory_option"
        [ -n "$destination" ] || refuse "install without a destination"
        inside_sandbox "$destination" \
            || refuse "install into '$destination' outside $SANDBOX_REAL"
        exec install "$@"
        ;;
    systemctl)
        inside_sandbox "${SONGMAKER_UNIT_DIR:-/etc/systemd/system}" \
            || refuse "systemctl with unit dir ${SONGMAKER_UNIT_DIR:-unset}" \
                      "outside $SANDBOX_REAL"
        # By path, not through PATH: which `systemctl` runs must not depend on
        # the order of a variable somebody could reorder.
        exec "$(dirname "$0")/systemctl" "$@"
        ;;
    *)
        # The installer's third shape: `sudo -u OPERATOR <script>` to run the
        # preflight unprivileged. Allowed only in that shape, and only for a
        # program that is itself inside the sandbox — an absolute path, since
        # a bare name would be resolved against the working directory and
        # that is precisely how `reboot` once got through.
        [ "$dropped_privilege" = "1" ] \
            || refuse "command '$command_name' — only install, systemctl, and" \
                      "a sandbox program under -u are modelled"
        inside_sandbox "$command_name" \
            || refuse "-u command '$command_name' outside $SANDBOX_REAL"
        exec "$command_name" "$@"
        ;;
esac

refuse "fell through the command table for '$command_name'"
"""

# Records what would have been asked of systemd, answers per unit, and — for
# the one command that has a real effect — runs the unit's ExecStart, because
# faking that away would have hidden the missing parent directory the mirror
# could not create. Everything it was not taught is refused: a fake that
# succeeds at a command nobody modelled is lying about what happened.
FAKE_SYSTEMCTL = '#!/bin/bash\nFAKE_NAME=systemctl\n' + CONTAINMENT + """
# A unit name reaches the filesystem twice below, so it may not carry a path.
valid_unit_name() {
    case "${1:-}" in
        "") return 1 ;;
        *[!A-Za-z0-9@_.-]*) return 1 ;;
        *..*) return 1 ;;
    esac
    return 0
}

inside_sandbox "${SONGMAKER_UNIT_DIR:-/etc/systemd/system}" \
    || refuse "unit dir ${SONGMAKER_UNIT_DIR:-unset} outside $SANDBOX_REAL"

# Both of these are writes, and both come from the environment rather than
# from the arguments — so they are checked like any other destination.
inside_sandbox "${SYSTEMCTL_LOG:-}" \
    || refuse "log ${SYSTEMCTL_LOG:-unset} outside $SANDBOX_REAL"
state_dir="$SANDBOX_ROOT/systemctl-state"
inside_sandbox "$state_dir" || refuse "state dir $state_dir outside $SANDBOX_REAL"

echo "$*" >> "$SYSTEMCTL_LOG"
mkdir -p "$state_dir"
# Answers per unit, not per repository: a fake that said yes for every unit
# would have let the preflight's path- and timer-checks pass without ever
# being exercised.
unit_of() { shift; for a in "$@"; do case "$a" in --*) ;; *) echo "$a"; return;; esac; done; }

operation="${1:-}"
case "$operation" in
    daemon-reload) exit 0 ;;
    enable|start|is-enabled|is-active|is-failed|list-unit-files) ;;
    *) refuse "unmodelled command '$operation'" ;;
esac

unit="$(unit_of "$@")"
valid_unit_name "$unit" || refuse "unit name '$unit' is not a plain unit name"

case "$operation" in
    enable)
        touch "$state_dir/$unit.enabled"
        case "$*" in *--now*) touch "$state_dir/$unit.active" ;; esac
        exit 0 ;;
    start)
        touch "$state_dir/$unit.active"
        file="$SONGMAKER_UNIT_DIR/$unit"
        [ -f "$file" ] || exit 1
        case "$unit" in
            *.service)
                exec_line="$(sed -n 's/^ExecStart=//p' "$file" | head -1)"
                [ -n "$exec_line" ] || exit 1
                # Only the program this unit names, and only if it lives in the
                # sandbox: a mutated unit could otherwise name any binary on
                # the machine and this fake would run it.
                inside_sandbox "${exec_line%% *}" \
                    || refuse "ExecStart '${exec_line%% *}' outside $SANDBOX_REAL"
                exec $exec_line ;;
        esac
        exit 0 ;;
    is-enabled) [ -e "$state_dir/$unit.enabled" ]; exit $? ;;
    is-active)  [ -e "$state_dir/$unit.active" ]; exit $? ;;
    is-failed)  [ -e "$state_dir/$unit.failed" ]; exit $? ;;
    list-unit-files)
        if [ -f "$SONGMAKER_UNIT_DIR/$unit" ]; then
            echo "$unit enabled enabled"
        fi
        exit 0 ;;
esac

refuse "fell through the operation table for '$operation'"
"""

# The installer reads the operator's home from passwd, never from $HOME (a run
# under `sudo -H` would otherwise mirror /root). The test therefore has to
# answer as passwd would.
FAKE_GETENT = """#!/bin/bash
if [ "$1" = "passwd" ]; then
    echo "$2:x:1000:1000::$FAKE_OPERATOR_HOME:/bin/bash"
    exit 0
fi
exit 2
"""


# What a test may not replace: everything that keeps the run inside the
# sandbox. SONGMAKER_UNIT_DIR is deliberately not on the list — pointing it at
# /etc/systemd/system is how the safety net itself is tested — because the
# fakes refuse that target rather than trusting the variable.
RESERVED_ENVIRONMENT = frozenset({
    "PATH", "SANDBOX_ROOT", "SANDBOX_REAL", "TMPDIR", "HOME",
})


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A git checkout that is its own main worktree, with the scripts in it."""
    root = tmp_path / "songmaker"
    (root / "scripts").mkdir(parents=True)
    for name in COPIED_SCRIPTS:
        source = REPO_ROOT / "scripts" / name
        target = root / "scripts" / name
        target.write_bytes(source.read_bytes())
        target.chmod(source.stat().st_mode)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A signed-in operator whose ~/.songmaker does not exist yet.

    That absence is the point: the mirror has to create the whole path, not
    just its last segment.
    """
    signed_in = tmp_path / "home"
    for relative, document in (
        (
            ".claude/.credentials.json",
            '{"claudeAiOauth": {"accessToken": "a", "expiresAt": 1, '
            '"scopes": ["user:inference"], "refreshToken": "secret"}}',
        ),
        (
            ".grok/auth.json",
            '{"realm": {"key": "k", "auth_mode": "oidc", "create_time": "t", '
            '"expires_at": "t", "user_id": "u", "team_id": "t", '
            '"principal_type": "User", "principal_id": "p", '
            '"oidc_issuer": "i", "oidc_client_id": "c", '
            '"coding_data_retention_opt_out": true, "refresh_token": "secret"}}',
        ),
        (
            ".codex/auth.json",
            '{"auth_mode": "chatgpt", "OPENAI_API_KEY": null, '
            '"last_refresh": "t", "tokens": {"id_token": "i", '
            '"access_token": "a", "account_id": "n", "refresh_token": "secret"}}',
        ),
    ):
        path = signed_in / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document)
    return signed_in


@pytest.fixture
def run_installer(tmp_path: Path, checkout: Path, home: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _executable(fake_bin / "sudo", FAKE_SUDO)
    _executable(fake_bin / "systemctl", FAKE_SYSTEMCTL)
    _executable(fake_bin / "getent", FAKE_GETENT)
    units = tmp_path / "systemd"
    units.mkdir()
    systemctl_log = tmp_path / "systemctl.log"
    systemctl_log.write_text("")

    scratch = tmp_path / "tmp"
    scratch.mkdir()

    def _run(
        *arguments: str,
        from_checkout: Path | None = None,
        **overrides: str,
    ) -> subprocess.CompletedProcess[str]:
        """Run the installer. Every invocation goes through here, always.

        There is deliberately no second way to start it: a test that built its
        own environment would be one PATH away from the real `sudo` and the
        real /etc/systemd/system the moment an early guard regressed.
        """
        started_from = from_checkout or checkout
        reserved = set(overrides) & RESERVED_ENVIRONMENT
        if reserved:
            raise AssertionError(
                f"a test may not override {sorted(reserved)}: those are what "
                f"keep the run inside the sandbox",
            )
        environment = {
            **os.environ,
            **overrides,
            # After the overrides, never before: these are the containment,
            # and a test that could replace PATH or SANDBOX_ROOT would be one
            # keyword argument away from the real sudo.
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "TMPDIR": str(scratch),
            "SANDBOX_ROOT": str(tmp_path),
            "SANDBOX_REAL": str(tmp_path.resolve()),
            "HOME": str(home),
            "SYSTEMCTL_LOG": str(systemctl_log),
            "FAKE_OPERATOR_HOME": str(home),
            "SONGMAKER_CLAUDE_CLI": "/bin/sh",
            "SONGMAKER_GROK_CLI": "/bin/sh",
            "SONGMAKER_CODEX_CLI": "/bin/sh",
        }
        environment.setdefault("SONGMAKER_UNIT_DIR", str(units))
        if "SONGMAKER_UNIT_DIR" in overrides:
            environment["SONGMAKER_UNIT_DIR"] = overrides["SONGMAKER_UNIT_DIR"]
        environment.pop("SONGMAKER_CLI_CREDENTIALS_DIR", None)
        return subprocess.run(
            [str(started_from / "scripts" / INSTALLER.name), *arguments],
            cwd=started_from,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    _run.units = units
    _run.log = systemctl_log
    _run.home = home
    _run.checkout = checkout
    _run.sandbox = tmp_path
    return _run


def test_the_installer_runs_through(run_installer) -> None:
    """The whole thing, end to end. Both shipped crashes died here."""
    result = run_installer()

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_it_writes_the_four_units_it_promises(run_installer) -> None:
    run_installer()

    installed = {path.name for path in run_installer.units.iterdir()}
    assert installed == {
        "songmaker-cli-credentials-mirror.service",
        "songmaker-cli-credentials-mirror.path",
        "songmaker-cli-credentials-mirror.timer",
        "songmaker-alert@.service",
    }


def test_the_unit_it_writes_names_this_checkout_and_this_home(
    run_installer, checkout: Path, home: Path,
) -> None:
    run_installer()

    unit = (run_installer.units / "songmaker-cli-credentials-mirror.service").read_text()
    exec_start = next(
        line for line in unit.splitlines() if line.startswith("ExecStart=")
    )
    assert str(checkout / "scripts" / "mirror_agent_cli_credentials.py") in exec_start
    assert f"--home {home}" in exec_start
    assert f"--mirror-dir {home}/.songmaker/agent-cli-credentials" in exec_start


def test_it_writes_the_mirror_even_though_songmaker_did_not_exist(
    run_installer, home: Path,
) -> None:
    """The default path is two levels deep; only creating the last one fails."""
    run_installer()

    mirrored = home / ".songmaker/agent-cli-credentials"
    assert {path.name for path in mirrored.iterdir()} >= {
        "claude.json", "grok.json", "codex.json",
    }


def test_no_renewal_secret_is_in_anything_it_published(
    run_installer, home: Path,
) -> None:
    run_installer()

    published = "\n".join(
        path.read_text()
        for path in (home / ".songmaker/agent-cli-credentials").glob("*.json")
    )
    assert "secret" not in published


def test_it_enables_the_units_rather_than_only_writing_them(run_installer) -> None:
    run_installer()

    asked = run_installer.log.read_text()
    assert "enable songmaker-cli-credentials-mirror.service" in asked
    assert "enable --now songmaker-cli-credentials-mirror.path" in asked
    assert "enable --now songmaker-cli-credentials-mirror.timer" in asked


def test_it_refuses_a_linked_worktree(run_installer, tmp_path) -> None:
    """These units outlive the shell; a throwaway checkout must not own them."""
    linked = _linked_worktree_of(run_installer.checkout, tmp_path)

    result = run_installer(from_checkout=linked)

    assert result.returncode == 1
    assert "linked worktree" in result.stderr


def test_the_fakes_and_not_the_machine_are_what_stop_a_real_target(
    run_installer,
) -> None:
    """From the MAIN checkout, so nothing earlier refuses first.

    The previous version of this test ran from a linked worktree and was
    stopped by require_main_checkout before a fake was ever consulted — it
    proved the guard, not the net under it. Pointed at /etc/systemd/system,
    the run must die on the fake, with the fake's own exit code, and leave the
    real directory untouched.
    """
    before = sorted(Path("/etc/systemd/system").glob("songmaker-cli-credentials-*"))

    result = run_installer(SONGMAKER_UNIT_DIR="/etc/systemd/system")

    assert result.returncode == 97, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "fake systemctl" in result.stderr or "fake sudo" in result.stderr
    assert sorted(Path("/etc/systemd/system").glob("songmaker-cli-credentials-*")) == before


@pytest.mark.parametrize(
    "escape",
    [
        "{sandbox}/../../../etc/systemd/system/evil.service",
        "relative/../../../../etc/systemd/system/evil.service",
        "{sandbox}/through-a-symlink/evil.service",
    ],
)
def test_the_fake_sudo_refuses_a_path_that_only_looks_contained(
    run_installer, tmp_path, escape,
) -> None:
    """Textual containment let `..` and symlinked parents through to real install."""
    (tmp_path / "through-a-symlink").symlink_to("/etc/systemd/system")
    # The source lives inside the sandbox on purpose: the destination is what
    # is under test, and an out-of-sandbox source would be refused first and
    # make the test pass without ever judging the escape.
    source = tmp_path / "unit-to-install"
    source.write_text("[Service]\n")

    result = subprocess.run(
        ["sudo", "install", "-m", "0644", str(source),
         escape.format(sandbox=tmp_path)],
        env={
            **os.environ,
            "PATH": f"{run_installer.sandbox / 'bin'}:{os.environ['PATH']}",
            "SANDBOX_ROOT": str(run_installer.sandbox),
            "SANDBOX_REAL": str(run_installer.sandbox.resolve()),
        },
        text=True, capture_output=True, check=False, cwd=tmp_path,
    )

    assert result.returncode == 97, result.stderr
    assert "fake sudo: refusing" in result.stderr


@pytest.mark.parametrize(
    ("argv", "why"),
    [
        # A command the installer never runs, and one with no path-shaped
        # argument — which is what a scan for paths saw nothing in.
        #
        # Deliberately harmless. The command that exposed this was `reboot`,
        # and putting it in a test meant a regressed fake took the operator's
        # machine down to report the regression. A test may not be able to do
        # that, however well guarded: `id` proves the same refusal and costs
        # nothing when the guard is gone.
        (["id"], "a command the installer never runs"),
        # The destination hides in an option value.
        (["install", "-m", "0644", "{source}",
          "--target-directory=/etc/systemd/system"], "--target-directory"),
        (["install", "-m", "0644", "{source}", "-t", "/etc/systemd/system"], "-t"),
    ],
)
def test_the_fake_sudo_runs_only_the_shapes_the_installer_uses(
    run_installer, tmp_path, argv, why,
) -> None:
    """An allowlist, not a scan: what is not listed does not run."""
    source = tmp_path / "unit-to-install"
    source.write_text("[Service]\n")

    result = subprocess.run(
        ["sudo", *[a.format(source=source) for a in argv]],
        env={
            **os.environ,
            "PATH": f"{run_installer.sandbox / 'bin'}:{os.environ['PATH']}",
            "SANDBOX_ROOT": str(run_installer.sandbox),
            "SANDBOX_REAL": str(run_installer.sandbox.resolve()),
        },
        text=True, capture_output=True, check=False, cwd=tmp_path,
    )

    assert result.returncode == 97, f"{why}: {result.stdout}{result.stderr}"
    assert "fake sudo: refusing" in result.stderr


def test_the_fake_systemctl_refuses_a_command_it_does_not_model(
    run_installer,
) -> None:
    """Succeeding at an unmodelled command would be the fake lying."""
    result = subprocess.run(
        ["systemctl", "mask", "songmaker-cli-credentials-mirror.service"],
        env={
            **os.environ,
            "PATH": f"{run_installer.sandbox / 'bin'}:{os.environ['PATH']}",
            "SANDBOX_ROOT": str(run_installer.sandbox),
            "SANDBOX_REAL": str(run_installer.sandbox.resolve()),
            "SONGMAKER_UNIT_DIR": str(run_installer.units),
            "SYSTEMCTL_LOG": str(run_installer.log),
        },
        text=True, capture_output=True, check=False,
    )

    assert result.returncode == 97
    assert "unmodelled command" in result.stderr


@pytest.mark.parametrize(
    ("exec_start", "why"),
    [
        ("/usr/bin/touch {canary}", "an absolute path outside the sandbox"),
        ("touch {canary}", "a bare name, resolved against the working directory"),
    ],
)
def test_the_fake_systemctl_will_not_run_an_execstart_outside_the_sandbox(
    run_installer, tmp_path, exec_start, why,
) -> None:
    """`systemctl start` really runs ExecStart, so ExecStart chooses a program.

    A mutated unit could otherwise name any binary on the machine and this
    fake would run it. The payload here is `touch` against a canary inside the
    sandbox: harmless if the guard is gone, and visible either way.
    """
    canary = tmp_path / "canary-should-not-exist"
    unit = run_installer.units / "probe.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(f"[Service]\nExecStart={exec_start.format(canary=canary)}\n")

    result = subprocess.run(
        ["systemctl", "start", "probe.service"],
        env={
            **os.environ,
            "PATH": f"{run_installer.sandbox / 'bin'}:{os.environ['PATH']}",
            "SANDBOX_ROOT": str(run_installer.sandbox),
            "SANDBOX_REAL": str(run_installer.sandbox.resolve()),
            "SONGMAKER_UNIT_DIR": str(run_installer.units),
            "SYSTEMCTL_LOG": str(run_installer.log),
        },
        text=True, capture_output=True, check=False, cwd=run_installer.sandbox,
    )

    assert result.returncode == 97, f"{why}: {result.stdout}{result.stderr}"
    assert "ExecStart" in result.stderr
    assert not canary.exists(), "the guard was gone and the program ran"


def test_the_fake_systemctl_refuses_a_unit_name_that_is_a_path(
    run_installer,
) -> None:
    """The unit name reaches the filesystem twice, so it may not traverse."""
    result = subprocess.run(
        ["systemctl", "start", "../../../evil.service"],
        env={
            **os.environ,
            "PATH": f"{run_installer.sandbox / 'bin'}:{os.environ['PATH']}",
            "SANDBOX_ROOT": str(run_installer.sandbox),
            "SANDBOX_REAL": str(run_installer.sandbox.resolve()),
            "SONGMAKER_UNIT_DIR": str(run_installer.units),
            "SYSTEMCTL_LOG": str(run_installer.log),
        },
        text=True, capture_output=True, check=False,
    )

    assert result.returncode == 97
    assert "not a plain unit name" in result.stderr


def test_a_test_cannot_override_what_keeps_the_run_contained(run_installer) -> None:
    with pytest.raises(AssertionError, match="keep the run inside the sandbox"):
        run_installer(PATH="/usr/bin:/bin")


def _linked_worktree_of(checkout: Path, tmp_path: Path) -> Path:
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


# Every unit the installer writes, and every way a stranger used to slip past.
FOREIGN_UNITS = {
    "service-another-checkout": (
        "songmaker-cli-credentials-mirror.service",
        "[Service]\nExecStart=/somewhere/else/mirror_agent_cli_credentials.py\n",
    ),
    # An unbounded prefix let this through: it starts with our script's path.
    "service-lookalike-suffix": (
        "songmaker-cli-credentials-mirror.service",
        "[Service]\nExecStart={mirror_script}.evil\n",
    ),
    # No directive at all: a file we cannot identify is the one to stop at.
    "service-unidentifiable": (
        "songmaker-cli-credentials-mirror.service",
        "[Service]\nType=oneshot\n",
    ),
    "path-another-home": (
        "songmaker-cli-credentials-mirror.path",
        "[Path]\nPathChanged=/home/someone-else/.claude/.credentials.json\n",
    ),
    # Same operator, different checkout: "somewhere under this home" is not
    # ownership, which is why the path unit is matched exactly.
    "path-same-home-other-file": (
        "songmaker-cli-credentials-mirror.path",
        "[Path]\nPathChanged={home}/.grok/auth.json\n",
    ),
    "timer-drives-another-service": (
        "songmaker-cli-credentials-mirror.timer",
        "[Timer]\nUnit=somebody-elses.service\n",
    ),
    # Unit= holds one value; anything after it is not ours. Treating it like a
    # command line, where a space starts the arguments, let this through.
    "timer-with-trailing-junk": (
        "songmaker-cli-credentials-mirror.timer",
        "[Timer]\nUnit=songmaker-cli-credentials-mirror.service other\n",
    ),
    "path-with-trailing-junk": (
        "songmaker-cli-credentials-mirror.path",
        "[Path]\nPathChanged={home}/.claude/.credentials.json other\n",
    ),
    # The first watch is ours, the ones after it are not. Reading only the
    # first PathChanged= line left these invisible.
    # Three right lines and a fourth foreign one: proving the expected watches
    # are present says nothing about what else the unit watches.
    "path-extra-foreign-watch": (
        "songmaker-cli-credentials-mirror.path",
        "[Path]\nPathChanged={home}/.claude/.credentials.json\n"
        "PathChanged={home}/.grok/auth.json\n"
        "PathChanged={home}/.codex/auth.json\n"
        "PathChanged=/home/someone-else/.claude/.credentials.json\n",
    ),
    # Same, through the other directive the unit legitimately uses.
    "path-extra-foreign-modified-watch": (
        "songmaker-cli-credentials-mirror.path",
        "[Path]\nPathChanged={home}/.claude/.credentials.json\n"
        "PathChanged={home}/.grok/auth.json\n"
        "PathChanged={home}/.codex/auth.json\n"
        "PathModified=/home/someone-else/.grok/auth.json\n",
    ),
    "path-foreign-watch-on-a-later-line": (
        "songmaker-cli-credentials-mirror.path",
        "[Path]\nPathChanged={home}/.claude/.credentials.json\n"
        "PathChanged=/home/someone-else/.grok/auth.json\n",
    ),
    "alert-another-checkout": (
        "songmaker-alert@.service",
        "[Service]\nExecStart=/somewhere/else/scripts/alert.sh \"subject\"\n",
    ),
}


@pytest.mark.parametrize("case", sorted(FOREIGN_UNITS))
def test_it_refuses_any_unit_that_belongs_to_something_else(
    run_installer, case,
) -> None:
    run_installer()
    name, body = FOREIGN_UNITS[case]
    unit = run_installer.units / name
    unit.write_text(
        body.format(
            mirror_script=run_installer.checkout
            / "scripts" / "mirror_agent_cli_credentials.py",
            home=run_installer.home,
        ),
    )

    result = run_installer()

    assert result.returncode == 1, f"stdout:\n{result.stdout}"
    assert "belongs to something else" in result.stderr


@pytest.mark.parametrize("case", sorted(FOREIGN_UNITS))
def test_force_takes_any_of_them_over(run_installer, case) -> None:
    run_installer()
    name, body = FOREIGN_UNITS[case]
    unit = run_installer.units / name
    unit.write_text(
        body.format(
            mirror_script=run_installer.checkout
            / "scripts" / "mirror_agent_cli_credentials.py",
            home=run_installer.home,
        ),
    )

    result = run_installer("--force")

    assert result.returncode == 0, f"stderr:\n{result.stderr}"
    assert "somewhere else" not in unit.read_text()


def test_our_own_unit_with_changed_arguments_is_still_ours(run_installer) -> None:
    """A guard that fired on every upgrade would be switched off within a week."""
    run_installer()
    unit = run_installer.units / "songmaker-cli-credentials-mirror.service"
    unit.write_text(unit.read_text().replace("--mirror-dir", "--verbose --mirror-dir"))

    result = run_installer()

    assert result.returncode == 0, f"stderr:\n{result.stderr}"


def test_a_refused_takeover_replaces_nothing_at_all(run_installer) -> None:
    """Every check before the first write: no half-installed machine."""
    run_installer()
    alert = run_installer.units / "songmaker-alert@.service"
    alert.write_text("[Service]\nExecStart=/untouched\n")
    unit = run_installer.units / "songmaker-cli-credentials-mirror.service"
    unit.write_text(
        unit.read_text().replace("ExecStart=", "ExecStart=/somewhere/else/", 1),
    )

    run_installer()

    assert alert.read_text() == "[Service]\nExecStart=/untouched\n"


# The preflight the installer ends with, and the auto-deploy tick calls on its
# own. Files that look right prove nothing about currency: something has to be
# running that rewrites them when the host refreshes a token.
PREFLIGHT_UNITS = (
    "songmaker-cli-credentials-mirror.service",
    "songmaker-cli-credentials-mirror.path",
    "songmaker-cli-credentials-mirror.timer",
)


def _run_preflight(
    run_installer, sabotage=None, path: str | None = None,
) -> subprocess.CompletedProcess[str]:
    run_installer()
    if sabotage is not None:
        sabotage()
    return subprocess.run(
        [
            str(run_installer.checkout / "scripts" / "check_agent_cli_mounts.sh"),
            "--home", str(run_installer.home),
            "--mirror-dir", str(run_installer.home / ".songmaker/agent-cli-credentials"),
        ],
        env={
            **os.environ,
            "PATH": path or f"{run_installer.sandbox / 'bin'}:{os.environ['PATH']}",
            "SANDBOX_ROOT": str(run_installer.sandbox),
            "SANDBOX_REAL": str(run_installer.sandbox.resolve()),
            "SYSTEMCTL_LOG": str(run_installer.log),
            "SONGMAKER_UNIT_DIR": str(run_installer.units),
            "SONGMAKER_CLAUDE_CLI": "/bin/sh",
            "SONGMAKER_GROK_CLI": "/bin/sh",
            "SONGMAKER_CODEX_CLI": "/bin/sh",
        },
        text=True, capture_output=True, check=False,
    )


@pytest.mark.parametrize(
    ("cli", "mirror_file"),
    [("claude", "claude.json"), ("grok", "grok.json"), ("codex", "codex.json")],
)
def test_a_missing_credential_file_fails_the_preflight(
    run_installer, cli, mirror_file,
) -> None:
    """Through the shell, not the Python function.

    The verifier call was deleted from this script once and nothing went red:
    its Python tests kept passing while the surface the deploy tick actually
    runs stopped checking anything at all.
    """
    mirrored = run_installer.home / ".songmaker/agent-cli-credentials"

    result = _run_preflight(run_installer, lambda: (mirrored / mirror_file).unlink())

    assert result.returncode == 1
    assert "is missing" in result.stderr


def test_a_hand_copied_login_fails_the_preflight(run_installer) -> None:
    """The invariant the whole arrangement exists for, checked where it counts."""
    mirrored = run_installer.home / ".songmaker/agent-cli-credentials"
    real_login = (run_installer.home / ".claude/.credentials.json").read_text()

    result = _run_preflight(
        run_installer,
        lambda: (mirrored / "claude.json").write_text(real_login),
    )

    assert result.returncode == 1
    assert "renewal token" in result.stderr


def test_a_world_readable_mirror_file_fails_the_preflight(run_installer) -> None:
    mirrored = run_installer.home / ".songmaker/agent-cli-credentials"

    result = _run_preflight(
        run_installer, lambda: (mirrored / "grok.json").chmod(0o644),
    )

    assert result.returncode == 1
    assert "0644" in result.stderr


def test_a_symlinked_mirror_file_fails_the_preflight(run_installer, tmp_path) -> None:
    mirrored = run_installer.home / ".songmaker/agent-cli-credentials"
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text("{}")

    def _swap() -> None:
        (mirrored / "codex.json").unlink()
        (mirrored / "codex.json").symlink_to(elsewhere)

    result = _run_preflight(run_installer, _swap)

    assert result.returncode == 1


def test_a_failed_mirror_service_fails_the_preflight(run_installer) -> None:
    """Live triggers and an old valid copy prove nothing about currency."""
    state = run_installer.sandbox / "systemctl-state"

    result = _run_preflight(
        run_installer,
        lambda: (state / "songmaker-cli-credentials-mirror.service.failed").touch(),
    )

    assert result.returncode == 1
    assert "failed state" in result.stderr


def test_the_preflight_says_so_when_it_cannot_ask_systemd(
    run_installer, tmp_path,
) -> None:
    """A minimal PATH with what the script needs — and no systemctl."""
    minimal = tmp_path / "minimal-bin"
    minimal.mkdir()
    for tool in ("dirname", "readlink", "env", "python3", "sed", "grep", "cut",
                 "getent", "id", "head", "cat", "mkdir", "bash"):
        found = shutil.which(tool)
        if found:
            (minimal / tool).symlink_to(found)

    result = _run_preflight(run_installer, path=str(minimal))

    assert result.returncode == 1
    assert "systemctl is not available" in result.stderr


def test_the_preflight_passes_once_everything_is_installed(run_installer) -> None:
    result = _run_preflight(run_installer)

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


@pytest.mark.parametrize("unit", PREFLIGHT_UNITS)
def test_an_uninstalled_unit_fails_the_preflight(run_installer, unit) -> None:
    result = _run_preflight(
        run_installer, lambda: (run_installer.units / unit).unlink(),
    )

    assert result.returncode == 1
    assert "is not installed" in result.stderr


@pytest.mark.parametrize("unit", PREFLIGHT_UNITS)
def test_a_disabled_unit_fails_the_preflight(run_installer, unit) -> None:
    state = run_installer.sandbox / "systemctl-state"

    result = _run_preflight(
        run_installer, lambda: (state / f"{unit}.enabled").unlink(),
    )

    assert result.returncode == 1
    assert "not enabled" in result.stderr


@pytest.mark.parametrize(
    "unit",
    [
        "songmaker-cli-credentials-mirror.path",
        "songmaker-cli-credentials-mirror.timer",
    ],
)
def test_a_stopped_trigger_fails_the_preflight(run_installer, unit) -> None:
    """Enabled only says "at the next boot"; nothing triggers the mirror now."""
    state = run_installer.sandbox / "systemctl-state"

    result = _run_preflight(
        run_installer, lambda: (state / f"{unit}.active").unlink(),
    )

    assert result.returncode == 1
    assert "is not running" in result.stderr


def test_it_refuses_to_install_units_that_would_run_as_root(run_installer) -> None:
    """A root login mirrors /root's logins, which are not the operator's."""
    result = run_installer(SUDO_USER="root")

    assert result.returncode == 1
    assert "would run as root" in result.stderr


def test_running_it_twice_changes_nothing_the_second_time(run_installer) -> None:
    run_installer()
    before = {
        path.name: path.read_text() for path in run_installer.units.iterdir()
    }

    result = run_installer()

    assert result.returncode == 0
    assert {p.name: p.read_text() for p in run_installer.units.iterdir()} == before
