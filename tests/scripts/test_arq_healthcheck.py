"""Behavioural test for the worker healthchecks, driven as the compose healthchecks run them."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.mark.parametrize(
    ("script", "arguments"),
    [("arq_healthcheck.py", ["scoring"]), ("music_worker_readiness.py", [])],
    ids=["scoring", "music"],
)
def test_the_healthcheck_fails_naming_redis_url_when_it_is_unset(
    script: str, arguments: list[str],
) -> None:
    environment = {key: value for key, value in os.environ.items() if key != "REDIS_URL"}

    result = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode != 0
    assert "REDIS_URL" in result.stderr
