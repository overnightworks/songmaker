"""Behavioral tests for monitoring/alertmanager-entrypoint.sh.

The entrypoint builds Alertmanager's config out of four .env values before
it starts the daemon (issue #333), and every value crosses two escaping
rules on the way in: YAML's single-quoted scalar and sed's replacement
text. What the operator wrote has to come back out of the generated file
byte for byte — ``o'connor@example.com`` is an ordinary address, and an
escaping mistake yields a config that only fails when the first real
alert tries to send.

The real script runs as itself on /bin/sh, with ``amtool`` and
``alertmanager`` replaced by fakes on PATH, and the file it writes is read
back with a real YAML parser rather than by matching text.
"""

from __future__ import annotations

import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = REPO_ROOT / "monitoring" / "alertmanager-entrypoint.sh"
TEMPLATE = REPO_ROOT / "monitoring" / "alertmanager.yml.template"

VALID_VALUES = {
    "ALERT_EMAIL_TO": "operator@example.com",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "songmaker@example.com",
}


@dataclass(frozen=True)
class EntrypointRun:
    result: subprocess.CompletedProcess[str]
    generated_config: Path
    alertmanager_argv: Path

    def config(self) -> dict:
        return yaml.safe_load(self.generated_config.read_text())


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run_entrypoint(
    tmp_path: Path,
    values: dict[str, str],
    password: str = "app password",
    amtool_exit_code: int = 0,
) -> EntrypointRun:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_executable(
        bin_dir / "amtool",
        f"#!/bin/sh\necho \"checked $2\"\nexit {amtool_exit_code}\n",
    )
    argv_file = tmp_path / "alertmanager-argv.txt"
    _write_executable(
        bin_dir / "alertmanager",
        f'#!/bin/sh\nprintf "%s" "$*" > "{argv_file}"\n',
    )
    secret_file = tmp_path / "smtp_password"
    secret_file.write_text(password)
    generated_config = tmp_path / "alertmanager.yml"

    result = subprocess.run(
        ["/bin/sh", str(ENTRYPOINT)],
        capture_output=True,
        text=True,
        timeout=10,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "ALERTMANAGER_CONFIG_TEMPLATE": str(TEMPLATE),
            "ALERTMANAGER_GENERATED_CONFIG": str(generated_config),
            "ALERTMANAGER_SMTP_PASSWORD_FILE": str(secret_file),
            **values,
        },
    )
    return EntrypointRun(result, generated_config, argv_file)


def test_a_plain_configuration_starts_the_daemon_on_the_generated_config(
    tmp_path: Path,
) -> None:
    run = _run_entrypoint(tmp_path, VALID_VALUES)

    assert run.result.returncode == 0, run.result.stderr
    config = run.config()
    assert config["global"]["smtp_smarthost"] == "smtp.example.com:587"
    assert config["receivers"][0]["email_configs"][0]["to"] == "operator@example.com"
    assert str(run.generated_config) in run.alertmanager_argv.read_text()


# Every one of these is a value an operator may legitimately hold: an
# apostrophe closes YAML's single-quoted scalar, and &, \ and | are sed's
# own syntax in the substitution that puts the value there.
AWKWARD_ADDRESSES = [
    "o'connor@example.com",
    "a&b@example.com",
    "back\\slash@example.com",
    "pipe|value@example.com",
    "it's-a&|\\-mess@example.com",
]


@pytest.mark.parametrize("address", AWKWARD_ADDRESSES)
def test_an_awkward_address_reaches_the_config_unchanged(
    tmp_path: Path, address: str,
) -> None:
    run = _run_entrypoint(
        tmp_path,
        {**VALID_VALUES, "ALERT_EMAIL_TO": address, "SMTP_USER": address},
    )

    assert run.result.returncode == 0, run.result.stderr
    config = run.config()
    assert config["receivers"][0]["email_configs"][0]["to"] == address
    assert config["global"]["smtp_from"] == address
    assert config["global"]["smtp_auth_username"] == address


@pytest.mark.parametrize(
    "unrepresentable", ["two\nlines@example.com", "carriage\rreturn@example.com"],
)
def test_a_line_break_is_refused_by_name_before_anything_is_written(
    tmp_path: Path, unrepresentable: str,
) -> None:
    run = _run_entrypoint(tmp_path, {**VALID_VALUES, "ALERT_EMAIL_TO": unrepresentable})

    assert run.result.returncode != 0
    assert "ALERT_EMAIL_TO" in run.result.stderr
    assert not run.generated_config.exists()
    assert not run.alertmanager_argv.exists()


@pytest.mark.parametrize("missing_key", sorted(VALID_VALUES))
def test_a_missing_value_is_refused_by_name(tmp_path: Path, missing_key: str) -> None:
    run = _run_entrypoint(
        tmp_path, {k: v for k, v in VALID_VALUES.items() if k != missing_key},
    )

    assert run.result.returncode != 0
    assert missing_key in run.result.stderr
    assert not run.alertmanager_argv.exists()


def test_an_empty_password_secret_refuses_to_start(tmp_path: Path) -> None:
    run = _run_entrypoint(tmp_path, VALID_VALUES, password="")

    assert run.result.returncode != 0
    assert "SMTP_PASSWORD" in run.result.stderr
    assert not run.alertmanager_argv.exists()


def test_the_password_stays_out_of_the_generated_config(tmp_path: Path) -> None:
    password = "app&password|with'quotes"

    run = _run_entrypoint(tmp_path, VALID_VALUES, password=password)

    assert run.result.returncode == 0, run.result.stderr
    assert password not in run.generated_config.read_text()
    assert (
        run.config()["global"]["smtp_auth_password_file"]
        == "/run/secrets/smtp_password"
    )


def test_a_config_alertmanagers_own_parser_rejects_stops_the_start(
    tmp_path: Path,
) -> None:
    """The daemon is never reached, so there is no crash-restart loop to
    read the reason out of."""
    run = _run_entrypoint(tmp_path, VALID_VALUES, amtool_exit_code=1)

    assert run.result.returncode != 0
    assert "not valid" in run.result.stderr
    assert not run.alertmanager_argv.exists()
