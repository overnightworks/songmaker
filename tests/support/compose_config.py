"""The real ``docker compose config`` rendering, driven from the repository root."""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import pytest
from support.repository_root import REPOSITORY_ROOT

COMPOSE_CONFIG_TIMEOUT_SECONDS: Final = 60


@functools.cache
def _require_docker_compose() -> None:
    if shutil.which("docker") is None:
        pytest.fail("docker is not on PATH; this test drives the real `docker compose config`")
    version = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        text=True,
        timeout=COMPOSE_CONFIG_TIMEOUT_SECONDS,
        check=False,
    )
    if version.returncode != 0:
        pytest.fail(f"`docker compose` is unavailable: {version.stderr.strip()}")


def run_compose_config(
    compose_args: Sequence[str],
    config_args: Sequence[str],
    *,
    env_file: Path,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    """Run the real ``docker compose config`` from the repository root.

    ``--env-file`` replaces the project's ``.env`` and the process environment is
    cleared down to PATH and HOME plus ``environment``, so neither the operator's
    file nor the test session's own environment reaches the rendering. ``config``
    needs only the Docker CLI's compose plugin, not a daemon.
    """
    _require_docker_compose()
    return subprocess.run(
        ["docker", "compose", "--env-file", str(env_file), *compose_args, "config", *config_args],
        cwd=REPOSITORY_ROOT,
        env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], **environment},
        capture_output=True,
        text=True,
        timeout=COMPOSE_CONFIG_TIMEOUT_SECONDS,
        check=False,
    )
