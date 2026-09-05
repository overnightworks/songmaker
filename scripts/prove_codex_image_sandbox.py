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
CODEX_READ_ONLY_BWRAP_ARGUMENTS = (
    "--unshare-user",
    "--unshare-net",
    "--ro-bind", "/", "/",
    "--",
    "/bin/true",
)


@dataclass(frozen=True)
class CommandResult:
    """The observable result of one Docker command."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str]], CommandResult]


def bubblewrap_probe_command() -> tuple[str, ...]:
    """Build the Bubblewrap form embedded in Codex's Linux binary."""
    return ("bwrap", *CODEX_READ_ONLY_BWRAP_ARGUMENTS)


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
    result = run(("docker", "compose", "exec", "-T", WEB_SERVICE, *bubblewrap_probe_command()))
    _required_output(result, "Codex Bubblewrap probe")


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
        *bubblewrap_probe_command()[1:],
    ))
    if result.returncode == 0:
        raise RuntimeError("Bubblewrap unexpectedly ran under docker-default")


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
