from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "prove_codex_image_sandbox.py"
_SPEC = importlib.util.spec_from_file_location("prove_codex_image_sandbox", _SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
proof = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = proof
_SPEC.loader.exec_module(proof)


def test_bubblewrap_probe_has_the_required_isolation_and_negative_checks() -> None:
    command = proof.bubblewrap_probe_command()
    shell_assertions = command[-1]

    assert command[:2] == ("bwrap", "--unshare-user")
    assert "--unshare-all" in command
    assert ("--ro-bind", "/", "/") == command[3:6]
    assert ("--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp") == command[6:12]
    assert ("--bind", proof.SANDBOX_CODEX_HOME, proof.SANDBOX_CODEX_HOME) == command[14:17]
    assert ("--remount-ro", "/tmp") == command[17:19]
    assert command[21] == proof.SANDBOX_CODEX_HOME
    assert "songmaker-sandbox-write-probe" in shell_assertions
    assert "outside-codex-home" in shell_assertions
    assert "NoNewPrivs:" in shell_assertions
    assert "CapEff:" in shell_assertions
    assert "1.1.1.1" in shell_assertions


def test_prove_checks_the_custom_profile_and_default_profile_negative_control() -> None:
    commands: list[tuple[str, ...]] = []

    def run(command: tuple[str, ...]) -> proof.CommandResult:
        commands.append(command)
        if command[:5] == ("docker", "compose", "ps", "-q", proof.WEB_SERVICE):
            return proof.CommandResult(0, "container-id\n", "")
        if command[:3] == ("docker", "inspect", "--format"):
            return proof.CommandResult(0, f"{proof.WEB_PROFILE}\n", "")
        if command[:4] == ("docker", "compose", "images", "-q"):
            return proof.CommandResult(0, "web-image\n", "")
        if command[:2] == ("docker", "run"):
            return proof.CommandResult(1, "", "bwrap: permission denied")
        return proof.CommandResult(0, "", "")

    proof.prove(run)

    assert any(command[:4] == ("docker", "compose", "exec", "-T") for command in commands)
    assert any(command[-2:] == ("-p", proof.SANDBOX_CODEX_HOME) for command in commands)
    reference = next(command for command in commands if command[:2] == ("docker", "run"))
    assert f"apparmor={proof.DEFAULT_DOCKER_PROFILE}" in reference
    assert "no-new-privileges:true" in reference


def test_prove_rejects_a_successful_docker_default_probe() -> None:
    def run(command: tuple[str, ...]) -> proof.CommandResult:
        if command[:5] == ("docker", "compose", "ps", "-q", proof.WEB_SERVICE):
            return proof.CommandResult(0, "container-id\n", "")
        if command[:3] == ("docker", "inspect", "--format"):
            return proof.CommandResult(0, f"{proof.WEB_PROFILE}\n", "")
        if command[:4] == ("docker", "compose", "images", "-q"):
            return proof.CommandResult(0, "web-image\n", "")
        return proof.CommandResult(0, "", "")

    with pytest.raises(RuntimeError, match="unexpectedly ran under docker-default"):
        proof.prove(run)
