"""The auto-deploy installer, driven through the recording fakes, writes the units' script paths."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from support.install_script_fakes import build_sandbox, copy_scripts, exec_start

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
    copy_scripts(checkout, AUTODEPLOY_FILES)
    sandbox = build_sandbox(tmp_path)

    result = subprocess.run(
        [str(checkout / "scripts" / "install_autodeploy.sh")],
        cwd=checkout,
        env=sandbox.environment(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return {
        "checkout": str(checkout),
        "autodeploy": (sandbox.units / "songmaker-autodeploy.service").read_text(),
        "alert": (sandbox.units / "songmaker-alert@.service").read_text(),
    }


def test_autodeploy_unit_runs_the_renamed_deploy_script(installed_units) -> None:
    command = exec_start(installed_units["autodeploy"])

    assert command == f"{installed_units['checkout']}/scripts/run_autodeploy.sh"


def test_alert_unit_starts_the_send_script_of_the_checkout(installed_units) -> None:
    command = exec_start(installed_units["alert"])

    assert command.startswith(f"{installed_units['checkout']}/scripts/send_alert.sh ")
