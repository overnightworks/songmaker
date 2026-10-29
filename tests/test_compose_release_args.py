"""The compose file passes the release build arguments to the images that serve the UI.

Each case renders the repository's docker-compose.yml through the real
``docker compose config --format json`` with a scratch ``--env-file`` and a
scratch project name, so the operator's ``.env`` and live project are never read.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from support.compose_config import run_compose_config

SCRATCH_PROJECT_COMPOSE_ARGS = (
    "-f", "docker-compose.yml", "-p", "songmaker-compose-release-args-test",
)
SCRATCH_REQUIRED = (
    "GRAFANA_PASSWORD=scratch-grafana-password-not-a-secret\n"
    "OIDC_ISSUER=https://keycloak.invalid/realms/scratch\n"
)
WEB_IMAGE_SERVICES = ("migrate", "songmaker-web")
RELEASE = {"SONGMAKER_RELEASE": "v2026.10.28.4", "SONGMAKER_COMMIT": "c" * 40}


def _render(
    tmp_path: Path, *config_args: str, environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    scratch_env_file = tmp_path / "scratch.env"
    scratch_env_file.write_text(SCRATCH_REQUIRED)
    return run_compose_config(
        SCRATCH_PROJECT_COMPOSE_ARGS,
        config_args,
        env_file=scratch_env_file,
        environment=environment,
    )


def _build_args(tmp_path: Path, environment: dict[str, str]) -> dict[str, dict[str, str]]:
    result = _render(tmp_path, "--format", "json", environment=environment)
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    return {name: service["build"].get("args", {}) for name, service in services.items()
            if "build" in service}


def test_both_web_image_services_build_with_the_same_release_arguments(
    tmp_path: Path,
) -> None:
    build_args = _build_args(tmp_path, RELEASE)

    assert build_args["migrate"] == RELEASE
    assert build_args["songmaker-web"] == RELEASE


def test_compose_accepts_a_build_without_release_arguments_and_passes_none(
    tmp_path: Path,
) -> None:
    quiet = _render(tmp_path, "--quiet", environment={})
    build_args = _build_args(tmp_path, {})

    assert quiet.returncode == 0, quiet.stderr
    assert {build_args[name].get("SONGMAKER_RELEASE") for name in WEB_IMAGE_SERVICES} == {None}
    assert {build_args[name].get("SONGMAKER_COMMIT") for name in WEB_IMAGE_SERVICES} == {None}
