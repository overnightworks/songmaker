#!/usr/bin/env python3
"""Prove the AppArmor-enabled Bubblewrap boundary in the running web service."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from agent_providers.sandbox.paths import (
    CODEX_HOME_DIRECTORY_NAME,
    CODEX_SANDBOX_PROOF_DIRECTORY,
)
from songmaker_cli.lifecycle import bubblewrap_startup_probe_command

WEB_SERVICE = "songmaker-web"
DEFAULT_WEB_PROFILE = "songmaker-web"
DEFAULT_DOCKER_PROFILE = "docker-default"
EMPTY_CAPABILITY_MASK = "0000000000000000"
SANDBOX_ROOT = f"/tmp/{CODEX_SANDBOX_PROOF_DIRECTORY}"
SANDBOX_CODEX_HOME = f"{SANDBOX_ROOT}/{CODEX_HOME_DIRECTORY_NAME}"
SANDBOX_WORKDIR = f"{SANDBOX_ROOT}/workdir"
CODEX_BINARY = "/usr/local/bin/codex"
_PROTECTED_CODEX_HOME_PATHS = (".git", ".agents", ".codex")
_NAMESPACE_DENIAL_OUTPUTS = (
    "No permissions to create a new namespace",
    "Operation not permitted",
    "EPERM",
)
_BUBBLEWRAP_NAMESPACE_PROBE_ARGUMENTS = (
    "--unshare-user",
    "--unshare-net",
    "--ro-bind", "/", "/",
    "/bin/true",
)
CODEX_READ_ONLY_PERMISSION_PROFILE = (
    '{"type":"managed","file_system":{"type":"restricted","entries":['
    '{"path":{"type":"special","value":{"kind":"root"}},"access":"read"},'
    f'{{"path":{{"type":"path","path":"{SANDBOX_CODEX_HOME}"}},"access":"write"}}'
    ']},"network":"restricted"}'
)


def refused_write_probe(path: str) -> str:
    """Shell fragment that fails the script when `path` is writable.

    `:` is a POSIX special builtin, so under dash a failed redirection on it
    (e.g. `: > path` against a read-only target) exits the *shell instance*
    outright instead of yielding a plain false exit status for the `if` to
    test — bash treats it as an ordinary false condition, dash does not. The
    subshell confines that fatal exit to itself; the enclosing `if` only ever
    observes the subshell's exit status, so a refused write reads as false on
    both shells and a successful write still reports the failure.
    """
    return f"""if ( : > "{path}" ) 2>/dev/null; then
  echo 'sandbox wrote outside CODEX_HOME' >&2
  exit 1
fi
"""


_SANDBOX_ASSERTIONS = f"""set -eu
: > "$CODEX_HOME/allowed"
{refused_write_probe("/app/songmaker-sandbox-write-probe")}\
{refused_write_probe("/tmp/outside-codex-home")}\
test "$(awk '/^NoNewPrivs:/ {{ print $2 }}' /proc/self/status)" = 1
test "$(awk '/^CapEff:/ {{ print $2 }}' /proc/self/status)" = "{EMPTY_CAPABILITY_MASK}"
""" + """/app/.venv/bin/python - <<'PY'
import socket

try:
    socket.create_connection(("1.1.1.1", 443), timeout=2)
except OSError:
    pass
else:
    raise SystemExit("sandbox network unexpectedly reachable")
PY
"""
_MASKED_PATH_ASSERTIONS = """set -eu
expect_permission_denied() {
  description="$1"
  shift

  if output="$("$@" 2>&1)"; then
    echo "system-path mask unexpectedly allowed: $description" >&2
    exit 1
  fi
  case "$output" in
    *"Permission denied"*) ;;
    *)
      echo "system-path mask did not report Permission denied: $description: $output" >&2
      exit 1
      ;;
  esac
}

for path in \\
  /proc/interrupts \\
  /proc/keys \\
  /proc/latency_stats \\
  /sys/devices/virtual/powercap \\
  /sys/firmware/memmap/1/type; do
  expect_permission_denied "$path" /bin/cat "$path"
done
"""
# DAC already denies this write to the unprivileged user, so it proves only that
# the mask section still exists, never the `deny /proc/sys w` rule itself.
_DAC_COVERED_MASK_WRITE_ASSERTION = """expect_permission_denied /proc/sys/kernel/shmmax \\
  /bin/sh -c 'printf x > "$1"' sh /proc/sys/kernel/shmmax
"""
_MASKED_PATH_ASSERTIONS += _DAC_COVERED_MASK_WRITE_ASSERTION
_SANDBOX_ASSERTIONS += _MASKED_PATH_ASSERTIONS


@dataclass(frozen=True)
class CommandResult:
    """The observable result of one Docker command."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str]], CommandResult]


def bubblewrap_probe_command() -> tuple[str, ...]:
    """Build Codex's traced read-only execution form with G4 assertions."""
    command = [
        "bwrap",
        "--new-session",
        "--die-with-parent",
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--bind", SANDBOX_CODEX_HOME, SANDBOX_CODEX_HOME,
    ]
    for protected_path in _PROTECTED_CODEX_HOME_PATHS:
        path = f"{SANDBOX_CODEX_HOME}/{protected_path}"
        command.extend(("--perms", "555", "--tmpfs", path, "--remount-ro", path))
    command.extend((
        "--unshare-user",
        "--unshare-pid",
        "--unshare-net",
        "--proc", "/proc",
        "--argv0",
        "codex-linux-sandbox",
        "--",
        CODEX_BINARY,
        "--sandbox-policy-cwd",
        SANDBOX_WORKDIR,
        "--command-cwd",
        SANDBOX_WORKDIR,
        "--permission-profile",
        CODEX_READ_ONLY_PERMISSION_PROFILE,
        "--apply-seccomp-then-exec",
        "--",
        "/bin/sh",
        "-ec",
        _SANDBOX_ASSERTIONS,
    ))
    return tuple(command)


def _run(command: Sequence[str]) -> CommandResult:
    completed = subprocess.run(command, capture_output=True, check=False, text=True)
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _required_output(result: CommandResult, description: str) -> str:
    if result.returncode == 0:
        return result.stdout.strip()
    raise RuntimeError(f"{description} failed:\n{result.stderr.strip()}")


def _verify_web_profile(run: CommandRunner, profile_name: str) -> None:
    container_id = _required_output(
        run(("docker", "compose", "ps", "-q", WEB_SERVICE)),
        f"finding the {WEB_SERVICE} container",
    )
    if not container_id:
        raise RuntimeError(f"{WEB_SERVICE} is not running")
    profile = _required_output(
        run(("docker", "inspect", "--format", "{{.AppArmorProfile}}", container_id)),
        f"reading {WEB_SERVICE}'s AppArmor profile",
    )
    if profile != profile_name:
        raise RuntimeError(
            f"{WEB_SERVICE} has AppArmor profile {profile!r}, expected {profile_name!r}"
        )


def _verify_sandbox(run: CommandRunner) -> None:
    prepare = run((
        "docker", "compose", "exec", "-T", WEB_SERVICE,
        "/bin/mkdir", "-p",
        SANDBOX_WORKDIR,
        *(f"{SANDBOX_CODEX_HOME}/{path}" for path in _PROTECTED_CODEX_HOME_PATHS),
    ))
    _required_output(prepare, "preparing the private CODEX_HOME probe directory")
    try:
        masked_paths = run((
            "docker", "compose", "exec", "-T", WEB_SERVICE,
            "/bin/sh", "-ec", _MASKED_PATH_ASSERTIONS,
        ))
        _required_output(masked_paths, "AppArmor system-path mask proof")
        startup_probe = run((
            "docker", "compose", "exec", "-T", WEB_SERVICE,
            *bubblewrap_startup_probe_command(),
        ))
        _required_output(startup_probe, "Codex Bubblewrap startup probe")
        result = run((
            "docker", "compose", "exec", "-T",
            "-e", f"CODEX_HOME={SANDBOX_CODEX_HOME}",
            WEB_SERVICE,
            *bubblewrap_probe_command(),
        ))
        _required_output(result, "Codex read-only sandbox proof")
    finally:
        run((
            "docker", "compose", "exec", "-T", WEB_SERVICE,
            "/bin/rm", "-rf", SANDBOX_CODEX_HOME,
        ))


def _verify_default_profile_still_blocks_bubblewrap(run: CommandRunner) -> None:
    image = _required_output(
        run(("docker", "compose", "images", "-q", WEB_SERVICE)),
        f"finding the {WEB_SERVICE} image",
    )
    if not image:
        raise RuntimeError(f"no image is available for {WEB_SERVICE}")
    result = run((
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        "songmaker",
        "--cap-drop=ALL",
        "--security-opt",
        f"apparmor={DEFAULT_DOCKER_PROFILE}",
        "--security-opt",
        "no-new-privileges:true",
        "--entrypoint",
        "bwrap",
        image,
        *_BUBBLEWRAP_NAMESPACE_PROBE_ARGUMENTS,
    ))
    if result.returncode == 0:
        raise RuntimeError("Bubblewrap unexpectedly ran under docker-default")
    if not any(denial in result.stderr for denial in _NAMESPACE_DENIAL_OUTPUTS):
        raise RuntimeError(
            "docker-default Bubblewrap probe did not fail while creating a namespace:\n"
            f"{result.stderr.strip()}"
        )


def prove(run: CommandRunner = _run, *, profile_name: str) -> None:
    """Check the named profile and the docker-default negative control."""
    _verify_web_profile(run, profile_name)
    _verify_sandbox(run)
    _verify_default_profile_still_blocks_bubblewrap(run)


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    """Read the AppArmor profile the running web service is proven against.

    A deployment that embeds this stack under another name proves that name;
    songmaker's own profile is the default.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "profile_name",
        nargs="?",
        default=DEFAULT_WEB_PROFILE,
        help=f"AppArmor profile {WEB_SERVICE} must run under (default: %(default)s)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    profile_name = parse_arguments(sys.argv[1:] if argv is None else argv).profile_name
    try:
        prove(profile_name=profile_name)
    except RuntimeError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(
        f"PASS: {WEB_SERVICE} runs Bubblewrap under {profile_name}; "
        f"{DEFAULT_DOCKER_PROFILE} blocks it."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
