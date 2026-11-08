"""The boot-autostart installer, driven through the recording fakes."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from support.install_script_fakes import (
    FAKE_SUDO,
    FAKE_SYSTEMCTL,
    INHERITED_ENVIRONMENT,
    linked_worktree_of,
    make_executable,
)
from support.repository_root import REPOSITORY_ROOT

AUTOSTART_FILES = (
    "agent_cli_paths.sh",
    "alert_config.sh",
    "send_alert.sh",
    "install_autostart.sh",
    "main_checkout.py",
    "songmaker-alert@.service",
    "songmaker.service",
)


@pytest.fixture
def run_autostart(tmp_path: Path):
    checkout = tmp_path / "songmaker"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    for name in AUTOSTART_FILES:
        source = REPOSITORY_ROOT / "scripts" / name
        target = scripts / name
        target.write_bytes(source.read_bytes())
        target.chmod(source.stat().st_mode)
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "sudo", FAKE_SUDO)
    make_executable(fake_bin / "systemctl", FAKE_SYSTEMCTL)
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
            [str(started_from / "scripts" / "install_autostart.sh"), *arguments],
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
    linked = linked_worktree_of(run_autostart.checkout, tmp_path)

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


def test_installer_writes_a_unit_without_preflight_or_mirror_requirement(
    run_autostart,
) -> None:
    result = run_autostart()

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    unit = (run_autostart.units / "songmaker.service").read_text()
    assert f"WorkingDirectory={run_autostart.checkout}" in unit
    assert "ExecStartPre" not in unit
    ordering = [
        line for line in unit.splitlines()
        if line.startswith(("After=", "Requires="))
    ]
    assert ordering
    assert not any("songmaker-cli-credentials-mirror" in line for line in ordering)


def test_installer_writes_an_alert_unit_that_starts_the_send_script_of_the_checkout(
    run_autostart,
) -> None:
    result = run_autostart()

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    alert_unit = (run_autostart.units / "songmaker-alert@.service").read_text()
    exec_start = next(
        line.removeprefix("ExecStart=")
        for line in alert_unit.splitlines()
        if line.startswith("ExecStart=")
    )
    assert exec_start.startswith(f"{run_autostart.checkout}/scripts/send_alert.sh ")
