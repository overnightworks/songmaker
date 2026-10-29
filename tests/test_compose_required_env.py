"""Compose fails closed without its required settings, against the real compose.

Grafana needs its password (#1357) and the web app needs its Keycloak issuer.
Each case runs the repository's docker-compose.yml through the real
``docker compose config --quiet`` — the same command the auto-deploy guard
runs — with a scratch ``--env-file`` and a scratch project name, so the
operator's ``.env`` and live project are never read.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from support.compose_config import run_compose_config

SCRATCH_PROJECT_COMPOSE_ARGS = (
    "-f", "docker-compose.yml", "-p", "songmaker-compose-required-env-test",
)
SCRATCH_PASSWORD = "scratch-grafana-password-not-a-secret"
SCRATCH_ISSUER = "https://keycloak.invalid/realms/scratch"
EVERYTHING_REQUIRED = {"GRAFANA_PASSWORD": SCRATCH_PASSWORD, "OIDC_ISSUER": SCRATCH_ISSUER}


def _env_file(**settings: str) -> str:
    return "".join(f"{name}={value}\n" for name, value in settings.items())


def _compose_config_quiet(
    tmp_path: Path, env_file: str, process_env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    scratch_env_file = tmp_path / "scratch.env"
    scratch_env_file.write_text(env_file)
    return run_compose_config(
        SCRATCH_PROJECT_COMPOSE_ARGS,
        ("--quiet",),
        env_file=scratch_env_file,
        environment=process_env,
    )


@pytest.mark.parametrize(
    ("env_file", "process_env"),
    [
        pytest.param(_env_file(**EVERYTHING_REQUIRED), {}, id="set-in-env-file"),
        pytest.param("", EVERYTHING_REQUIRED, id="set-only-in-process-env"),
    ],
)
def test_compose_accepts_the_required_settings_without_printing_the_password(
    tmp_path: Path, env_file: str, process_env: dict[str, str],
) -> None:
    result = _compose_config_quiet(tmp_path, env_file, process_env)

    assert result.returncode == 0, result.stderr
    assert SCRATCH_PASSWORD not in result.stdout + result.stderr


@pytest.mark.parametrize("required", sorted(EVERYTHING_REQUIRED))
@pytest.mark.parametrize("state", ["empty", "missing"])
def test_compose_refuses_without_a_required_setting_and_names_it(
    tmp_path: Path, required: str, state: str,
) -> None:
    others = {name: value for name, value in EVERYTHING_REQUIRED.items() if name != required}
    env_file = _env_file(**others) + (f"{required}=\n" if state == "empty" else "")

    result = _compose_config_quiet(tmp_path, env_file, {})

    assert result.returncode != 0
    assert f"{required} must be set in .env" in result.stderr
