from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
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


@pytest.fixture
def dash() -> str:
    dash_path = shutil.which("dash")
    if dash_path is None:
        pytest.skip("dash is not installed on this host")
    if os.geteuid() == 0:
        pytest.skip("root ignores a 0o555 directory, so a refused write cannot be proven")
    return dash_path


def run_probe_under_dash(
    dash: str, path: Path, *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    script = f"""set -eu
{proof.refused_write_probe(str(path))}\
echo probe-passed
"""
    return subprocess.run(
        [dash, "-c", script], capture_output=True, text=True, cwd=cwd
    )


def test_bubblewrap_probe_matches_the_traced_codex_read_only_execution_form() -> None:
    command = proof.bubblewrap_probe_command()

    assert command[:11] == (
        "bwrap",
        "--new-session",
        "--die-with-parent",
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--bind", proof.SANDBOX_CODEX_HOME, proof.SANDBOX_CODEX_HOME,
    )
    expected_home_overlays = tuple(
        argument
        for protected_path in proof._PROTECTED_CODEX_HOME_PATHS
        for argument in (
            "--perms",
            "555",
            "--tmpfs",
            f"{proof.SANDBOX_CODEX_HOME}/{protected_path}",
            "--remount-ro",
            f"{proof.SANDBOX_CODEX_HOME}/{protected_path}",
        )
    )
    assert command[11:29] == expected_home_overlays
    assert command[29:-4] == (
        "--unshare-user",
        "--unshare-pid",
        "--unshare-net",
        "--proc", "/proc",
        "--argv0", "codex-linux-sandbox",
        "--",
        proof.CODEX_BINARY,
        "--sandbox-policy-cwd", proof.SANDBOX_WORKDIR,
        "--command-cwd", proof.SANDBOX_WORKDIR,
        "--permission-profile", proof.CODEX_READ_ONLY_PERMISSION_PROFILE,
        "--apply-seccomp-then-exec",
    )
    assert command[-4:-1] == ("--", "/bin/sh", "-ec")
    assertions = command[-1]
    assert "songmaker-sandbox-write-probe" in assertions
    assert "outside-codex-home" in assertions
    assert "NoNewPrivs:" in assertions
    assert "CapEff:" in assertions
    assert f'"{proof.EMPTY_CAPABILITY_MASK}"' in assertions
    assert "EMPTY_CAPABILITY_MASK" not in assertions
    assert "1.1.1.1" in assertions
    for path in (
        "/proc/interrupts",
        "/proc/keys",
        "/proc/latency_stats",
        "/sys/devices/virtual/powercap",
        "/sys/firmware/memmap/1/type",
        "/proc/sys/kernel/shmmax",
    ):
        assert path in assertions
    assert "Permission denied" in assertions


def test_refused_write_probe_reads_a_refused_write_as_false_under_dash(
    dash: str, tmp_path: Path
) -> None:
    read_only_directory = tmp_path / "read-only"
    read_only_directory.mkdir(mode=0o555)
    refused_target = read_only_directory / "sandbox-write-probe"

    result = run_probe_under_dash(dash, refused_target)

    assert result.returncode == 0
    assert result.stdout.strip() == "probe-passed"
    assert not refused_target.exists()


def test_refused_write_probe_still_fails_the_script_on_a_successful_write(
    dash: str, tmp_path: Path
) -> None:
    writable_target = tmp_path / "sandbox-write-probe"

    result = run_probe_under_dash(dash, writable_target)

    assert result.returncode == 1
    assert "sandbox wrote outside CODEX_HOME" in result.stderr
    assert "probe-passed" not in result.stdout
    assert writable_target.exists()


def test_refused_write_probe_quotes_a_path_containing_a_space(
    dash: str, tmp_path: Path
) -> None:
    target = tmp_path / "sp ace" / "x"

    result = run_probe_under_dash(dash, target, cwd=tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == "probe-passed"
    assert list(tmp_path.iterdir()) == []


def test_bubblewrap_startup_probe_matches_the_traced_codex_preflight_form() -> None:
    assert proof.bubblewrap_startup_probe_command() == (
        "bwrap",
        "--new-session",
        "--die-with-parent",
        "--tmpfs", "/",
        "--dev", "/dev",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/etc", "/etc",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", "/sbin", "/sbin",
        "--ro-bind", "/usr", "/usr",
        "--unshare-user",
        "--unshare-pid",
        "--unshare-net",
        "--proc", "/proc",
        "--",
        "/usr/bin/true",
    )


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
            return proof.CommandResult(
                1, "", "bwrap: No permissions to create a new namespace"
            )
        return proof.CommandResult(0, "", "")

    proof.prove(run)

    prepare = next(
        command
        for command in commands
        if command[:4] == ("docker", "compose", "exec", "-T") and "/bin/mkdir" in command
    )
    assert f"{proof.SANDBOX_CODEX_HOME}/.codex" in prepare
    assert (
        "docker",
        "compose",
        "exec",
        "-T",
        proof.WEB_SERVICE,
        *proof.bubblewrap_startup_probe_command(),
    ) in commands
    assert (
        "docker",
        "compose",
        "exec",
        "-T",
        proof.WEB_SERVICE,
        "/bin/sh",
        "-ec",
        proof._MASKED_PATH_ASSERTIONS,
    ) in commands
    sandbox = next(
        command
        for command in commands
        if command[:4] == ("docker", "compose", "exec", "-T") and "CODEX_HOME=" in " ".join(command)
    )
    assert f"CODEX_HOME={proof.SANDBOX_CODEX_HOME}" in sandbox
    reference = next(command for command in commands if command[:2] == ("docker", "run"))
    assert f"apparmor={proof.DEFAULT_DOCKER_PROFILE}" in reference
    assert reference[3:5] == ("--network", "none")
    assert "no-new-privileges:true" in reference
    assert reference[-len(proof._BUBBLEWRAP_NAMESPACE_PROBE_ARGUMENTS):] == (
        proof._BUBBLEWRAP_NAMESPACE_PROBE_ARGUMENTS
    )
    assert proof.CODEX_BINARY not in reference
    assert "CODEX_HOME=" not in " ".join(reference)


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


def test_prove_rejects_a_non_namespace_docker_default_failure() -> None:
    def run(command: tuple[str, ...]) -> proof.CommandResult:
        if command[:5] == ("docker", "compose", "ps", "-q", proof.WEB_SERVICE):
            return proof.CommandResult(0, "container-id\n", "")
        if command[:3] == ("docker", "inspect", "--format"):
            return proof.CommandResult(0, f"{proof.WEB_PROFILE}\n", "")
        if command[:4] == ("docker", "compose", "images", "-q"):
            return proof.CommandResult(0, "web-image\n", "")
        if command[:2] == ("docker", "run"):
            return proof.CommandResult(1, "", "bwrap: executable not found")
        return proof.CommandResult(0, "", "")

    with pytest.raises(RuntimeError, match="did not fail while creating a namespace"):
        proof.prove(run)
