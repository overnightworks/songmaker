"""The e2e stack's session seeder runs inside the web image against the app's own settings."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SEEDER = Path(__file__).parents[2] / "frontend" / "e2e" / "support" / "seed_sessions.py"
REQUEST_VARIABLE = "SEED_SESSIONS_REQUEST"
SEEDER_SECONDS = 60


def test_the_seeder_signs_an_account_in_on_the_apps_settings(web_cluster) -> None:
    cluster, _ = web_cluster
    request = json.dumps({"seed": [{"username": "e2e-seeded"}]})

    finished = subprocess.run(
        [sys.executable, "-"],
        input=SEEDER.read_text(encoding="utf-8"),
        env={**os.environ, **cluster.environment, REQUEST_VARIABLE: request},
        capture_output=True, text=True, timeout=SEEDER_SECONDS, check=False,
    )

    assert finished.returncode == 0, finished.stderr
    [seeded] = json.loads(finished.stdout)
    assert (seeded["username"], bool(seeded["session_cookie_value"])) == ("e2e-seeded", True)
