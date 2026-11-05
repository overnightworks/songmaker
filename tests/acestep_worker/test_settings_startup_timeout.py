"""The ACE-Step startup timeout is one number: Python default and Compose fallback agree.

The Compose fallback is read from the real ``docker compose config`` with a scratch
``--env-file``, so neither the operator's ``.env`` nor the live project is read.
"""

from __future__ import annotations

import json
from pathlib import Path

from support.compose_config import run_compose_config

from acestep_worker.settings import WorkerSettings
from songmaker_cli.constants import GENERATE_LOAD_MODEL_TIMEOUT_SECONDS

ACESTEP_WORKER_SERVICE = "songmaker-acestep-worker-0"
SCRATCH_ENVIRONMENT = {
    "GRAFANA_PASSWORD": "scratch-grafana-password-not-a-secret",
    "OIDC_ISSUER": "https://keycloak.invalid/realms/scratch",
}


def test_compose_fallback_equals_the_python_default_and_ends_before_the_scheduler_gives_up(
    tmp_path: Path,
) -> None:
    scratch_env_file = tmp_path / "scratch.env"
    scratch_env_file.write_text("")
    result = run_compose_config(
        ("-f", "docker-compose.yml", "-p", "songmaker-startup-timeout-test"),
        ("--format", "json"),
        env_file=scratch_env_file,
        environment=SCRATCH_ENVIRONMENT,
    )
    assert result.returncode == 0, result.stderr
    service = json.loads(result.stdout)["services"][ACESTEP_WORKER_SERVICE]
    compose_fallback = int(service["environment"]["ACESTEP_STARTUP_TIMEOUT_SECONDS"])
    settings = WorkerSettings(
        worker_id="w", redis_url="redis://fake", songmaker_internal_token="t",
    )
    eviction_seconds = (
        settings.acestep_shutdown_grace_seconds + settings.acestep_shutdown_kill_seconds
    )

    assert compose_fallback == settings.acestep_startup_timeout_seconds
    assert compose_fallback + eviction_seconds < GENERATE_LOAD_MODEL_TIMEOUT_SECONDS
