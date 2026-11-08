"""The auto-deploy installer, driven through the recording fakes, writes the units' script paths."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from support.install_script_fakes import (
    FAKE_SUDO,
    FAKE_SYSTEMCTL,
    INHERITED_ENVIRONMENT,
    make_executable,
)
from support.repository_root import REPOSITORY_ROOT

AUTODEPLOY_FILES = (
    "alert_config.sh",
    "install_autodeploy.sh",
    "run_autodeploy.sh",
    "send_alert.sh",
    "songmaker-alert@.service",
    "songmaker-autodeploy.service",
    "songmaker-autodeploy.timer",
)


@pytest.fixture
def installed_units(tmp_path: Path) -> dict[str, str]:
    checkout = tmp_path / "songmaker"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    for name in AUTODEPLOY_FILES:
        source = REPOSITORY_ROOT / "scripts" / name
        target = scripts / name
        target.write_bytes(source.read_bytes())
        target.chmod(source.stat().st_mode)

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
    environment = {
        name: os.environ[name] for name in INHERITED_ENVIRONMENT if name in os.environ
    }
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

    result = subprocess.run(
        [str(scripts / "install_autodeploy.sh")],
        cwd=checkout,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return {
        "checkout": str(checkout),
        "autodeploy": (units / "songmaker-autodeploy.service").read_text(),
        "alert": (units / "songmaker-alert@.service").read_text(),
    }


def _exec_start(unit: str) -> str:
    return next(
        line.removeprefix("ExecStart=")
        for line in unit.splitlines()
        if line.startswith("ExecStart=")
    )


def test_autodeploy_unit_runs_the_renamed_deploy_script(installed_units) -> None:
    exec_start = _exec_start(installed_units["autodeploy"])

    assert exec_start == f"{installed_units['checkout']}/scripts/run_autodeploy.sh"


def test_alert_unit_starts_the_send_script_of_the_checkout(installed_units) -> None:
    exec_start = _exec_start(installed_units["alert"])

    assert exec_start.startswith(f"{installed_units['checkout']}/scripts/send_alert.sh ")
