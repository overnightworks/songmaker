"""The boot-autostart installer, driven through the recording fakes."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from test_install_cli_credentials_mirror import (
    FAKE_SUDO,
    FAKE_SYSTEMCTL,
    INHERITED_ENVIRONMENT,
    REPO_ROOT,
    _executable,
    _linked_worktree_of,
)

AUTOSTART_FILES = (
    "agent-cli-paths.sh",
    "alert-config.sh",
    "alert.sh",
    "check_agent_cli_mounts.sh",
    "install-autostart.sh",
    "songmaker-alert@.service",
    "songmaker.service",
)


@pytest.fixture
def run_autostart(tmp_path: Path):
    checkout = tmp_path / "songmaker"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    for name in AUTOSTART_FILES:
        source = REPO_ROOT / "scripts" / name
        target = scripts / name
        target.write_bytes(source.read_bytes())
        target.chmod(source.stat().st_mode)
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _executable(fake_bin / "sudo", FAKE_SUDO)
    _executable(fake_bin / "systemctl", FAKE_SYSTEMCTL)
    units = tmp_path / "systemd"
    units.mkdir()
    recording = tmp_path / "recording"
    recording.write_text("")
    (tmp_path / "systemctl-state").write_text("")
    scratch = tmp_path / "tmp"
    scratch.mkdir()

    def _environment(**overrides: str) -> dict[str, str]:
        environment = {
            name: os.environ[name]
            for name in INHERITED_ENVIRONMENT
            if name in os.environ
        }
        environment.update(overrides)
        environment.update(
            {
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "TMPDIR": str(scratch),
                "SANDBOX_ROOT": str(tmp_path),
                "RECORDING": str(recording),
                "SONGMAKER_UNIT_DIR": str(units),
                "SUDO_USER": "operator",
            },
        )
        return environment

    def _run(
        *arguments: str, from_checkout: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        started_from = from_checkout or checkout
        return subprocess.run(
            [str(started_from / "scripts" / "install-autostart.sh"), *arguments],
            cwd=started_from,
            env=_environment(),
            text=True,
            capture_output=True,
            check=False,
        )

    _run.checkout = checkout
    _run.recording = recording
    _run.units = units
    _run.sandbox = tmp_path
    return _run


def test_installer_refuses_a_linked_worktree(run_autostart, tmp_path: Path) -> None:
    linked = _linked_worktree_of(run_autostart.checkout, tmp_path)

    result = run_autostart(from_checkout=linked)

    assert result.returncode == 1
    assert "linked worktree" in result.stderr
    assert not run_autostart.recording.read_text()


def test_installer_refuses_a_foreign_unit_without_an_ownership_marker(
    run_autostart,
) -> None:
    unit = run_autostart.units / "songmaker.service"
    unit.write_text("[Service]\nType=oneshot\n")

    result = run_autostart()

    assert result.returncode == 1
    assert "belongs to something else" in result.stderr
    assert unit.read_text() == "[Service]\nType=oneshot\n"
    assert not run_autostart.recording.read_text()


@pytest.mark.parametrize(
    "working_directory",
    ("", "WorkingDirectory=/another/checkout\n"),
)
def test_installer_refuses_matching_compose_commands_from_another_checkout(
    run_autostart, working_directory: str,
) -> None:
    unit = run_autostart.units / "songmaker.service"
    body = (
        "[Service]\n"
        "ExecStart=/usr/bin/docker compose up -d\n"
        f"{working_directory}"
    )
    unit.write_text(body)

    result = run_autostart()

    assert result.returncode == 1
    assert "belongs to something else" in result.stderr
    assert unit.read_text() == body
    assert not run_autostart.recording.read_text()


def test_installed_unit_requires_the_mirror_and_runs_argumentless_preflight(
    run_autostart,
) -> None:
    result = run_autostart()

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    unit = (run_autostart.units / "songmaker.service").read_text()
    checkout = run_autostart.checkout
    assert (
        "After=docker.service songmaker-cli-credentials-mirror.service" in unit
    )
    assert (
        "Requires=docker.service songmaker-cli-credentials-mirror.service" in unit
    )
    assert f"WorkingDirectory={checkout}" in unit
    assert (
        f"ExecStartPre={checkout}/scripts/check_agent_cli_mounts.sh" in unit
    )
    assert "--home" not in unit
    assert "--mirror-dir" not in unit
    assert (
        f"sudo -u operator {checkout}/scripts/check_agent_cli_mounts.sh"
        in run_autostart.recording.read_text().splitlines()
    )
