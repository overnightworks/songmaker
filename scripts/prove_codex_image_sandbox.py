#!/usr/bin/env python3
"""Prove the AppArmor-enabled Bubblewrap boundary in the running web service."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

WEB_SERVICE = "songmaker-web"
WEB_PROFILE = "songmaker-web"
DEFAULT_DOCKER_PROFILE = "docker-default"
EMPTY_CAPABILITY_MASK = "0000000000000000"
SANDBOX_CODEX_HOME = "/tmp/songmaker-codex-sandbox-probe/codex-home"
SANDBOX_WORKDIR = "/tmp/songmaker-codex-sandbox-probe/workdir"
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
_SANDBOX_ASSERTIONS = f"""set -eu
: > "$CODEX_HOME/allowed"
if : > /app/songmaker-sandbox-write-probe; then
  echo 'sandbox wrote outside CODEX_HOME' >&2
  exit 1
fi
if : > /tmp/outside-codex-home; then
  echo 'sandbox wrote outside CODEX_HOME' >&2
  exit 1
fi
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


def _verify_web_profile(run: CommandRunner) -> None:
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
    if profile != WEB_PROFILE:
        raise RuntimeError(
            f"{WEB_SERVICE} has AppArmor profile {profile!r}, expected {WEB_PROFILE!r}"
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


def prove(run: CommandRunner = _run) -> None:
    """Check the positive profile and the docker-default negative control."""
    _verify_web_profile(run)
    _verify_sandbox(run)
    _verify_default_profile_still_blocks_bubblewrap(run)


def main() -> int:
    try:
        prove()
    except RuntimeError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("PASS: songmaker-web runs Bubblewrap under songmaker-web; docker-default blocks it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
