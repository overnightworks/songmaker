"""Compose hands songmaker's own secrets to its services as files, never as environment.

Each case renders the repository's docker-compose.yml through the real
``docker compose config --format json`` with a scratch ``--env-file`` and a
scratch project name, so the operator's ``.env`` and live project are never read.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from support.compose_config import run_compose_config

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import secret_files  # noqa: E402 - needs scripts on sys.path first

SCRATCH_PROJECT_COMPOSE_ARGS = (
    "-f", "docker-compose.yml", "-p", "songmaker-compose-secret-files-test",
)
SCRATCH_REQUIRED = (
    "GRAFANA_PASSWORD=scratch-grafana-password-not-a-secret\n"
    "OIDC_ISSUER=https://keycloak.invalid/realms/scratch\n"
)
SECRET_ENVIRONMENT_KEYS = (
    "POSTGRES_PASSWORD",
    "SESSION_SECRET",
    "SONGMAKER_INTERNAL_TOKEN",
    "SONGMAKER_MONITORING_TOKEN",
)
SCRATCH_VALUE = "scratch-value-not-a-secret"


def _rendered_compose(tmp_path: Path, environment: dict[str, str]) -> dict:
    scratch_env_file = tmp_path / "scratch.env"
    scratch_env_file.write_text(SCRATCH_REQUIRED)
    result = run_compose_config(
        SCRATCH_PROJECT_COMPOSE_ARGS,
        ("--format", "json"),
        env_file=scratch_env_file,
        environment=environment,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _songmaker_secret_directories(rendered: dict) -> set[Path]:
    return {
        Path(secret["file"]).parent
        for name, secret in rendered["secrets"].items()
        if name in {"session_secret", "postgres_password", "songmaker_internal_token",
                    "songmaker_monitoring_token"}
    }


def test_the_secret_files_default_to_the_directory_the_verify_check_compares(tmp_path: Path) -> None:
    rendered = _rendered_compose(tmp_path, {})

    assert _songmaker_secret_directories(rendered) == {Path.home() / secret_files.DEFAULT_DIRECTORY}


def test_the_secret_files_follow_the_configured_secrets_directory(tmp_path: Path) -> None:
    rendered = _rendered_compose(tmp_path, {"SONGMAKER_SECRETS_DIR": str(tmp_path / "elsewhere")})

    assert _songmaker_secret_directories(rendered) == {tmp_path / "elsewhere"}


@pytest.mark.parametrize("key", SECRET_ENVIRONMENT_KEYS)
def test_no_service_receives_a_secret_as_an_environment_variable(
    tmp_path: Path, key: str,
) -> None:
    rendered = _rendered_compose(tmp_path, {key: SCRATCH_VALUE})

    assert SCRATCH_VALUE not in json.dumps(rendered)
    for name, service in rendered["services"].items():
        assert key not in service.get("environment", {}), name
