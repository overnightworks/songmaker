"""Behavioural test for scripts/arq_healthcheck.py, driven as the compose healthcheck runs it."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "arq_healthcheck.py"


def test_the_healthcheck_fails_naming_redis_url_when_it_is_unset() -> None:
    environment = {key: value for key, value in os.environ.items() if key != "REDIS_URL"}

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "music"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode != 0
    assert "REDIS_URL" in result.stderr
