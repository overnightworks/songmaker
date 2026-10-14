"""Grafana fails closed without its password (#1357), against the real compose.

Each case runs the repository's docker-compose.yml through the real
``docker compose config --quiet`` — the same command the auto-deploy guard
runs — with a scratch ``--env-file``, an environment cleared down to PATH and
HOME, and a scratch project name. ``--env-file`` replaces the project's
``.env``, so the operator's file and live project are never read.
``config`` needs only the Docker CLI's compose plugin, not a daemon.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
SCRATCH_PROJECT = "songmaker-compose-required-env-test"
SCRATCH_PASSWORD = "scratch-grafana-password-not-a-secret"
COMPOSE_TIMEOUT_SECONDS = 60


@pytest.fixture(scope="module", autouse=True)
def _require_docker_compose() -> None:
    try:
        version = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=COMPOSE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        pytest.fail("docker is not on PATH; this module drives the real `docker compose config`")
    if version.returncode != 0:
        pytest.fail(f"`docker compose` is unavailable: {version.stderr.strip()}")


def _compose_config_quiet(
    tmp_path: Path, env_file: str, process_env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    scratch_env_file = tmp_path / "scratch.env"
    scratch_env_file.write_text(env_file)
    return subprocess.run(
        [
            "docker", "compose",
            "-f", str(COMPOSE_FILE),
            "-p", SCRATCH_PROJECT,
            "--env-file", str(scratch_env_file),
            "config", "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=COMPOSE_TIMEOUT_SECONDS,
        cwd=tmp_path,
        env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], **process_env},
    )


@pytest.mark.parametrize(
    ("env_file", "process_env"),
    [
        pytest.param(f"GRAFANA_PASSWORD={SCRATCH_PASSWORD}\n", {}, id="set-in-env-file"),
        pytest.param("", {"GRAFANA_PASSWORD": SCRATCH_PASSWORD}, id="set-only-in-process-env"),
    ],
)
def test_compose_accepts_a_grafana_password_without_printing_it(
    tmp_path: Path, env_file: str, process_env: dict[str, str],
) -> None:
    result = _compose_config_quiet(tmp_path, env_file, process_env)

    assert result.returncode == 0, result.stderr
    assert SCRATCH_PASSWORD not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "env_file",
    [
        pytest.param("GRAFANA_PASSWORD=\n", id="empty"),
        pytest.param("", id="missing"),
    ],
)
def test_compose_refuses_without_a_grafana_password_and_names_it(
    tmp_path: Path, env_file: str,
) -> None:
    result = _compose_config_quiet(tmp_path, env_file, {})

    assert result.returncode != 0
    assert "GRAFANA_PASSWORD must be set in .env" in result.stderr
