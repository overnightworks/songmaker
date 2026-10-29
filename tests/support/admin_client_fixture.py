"""A client signed in as an admin on a fresh test database."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.admin_client import build_admin_client

from songmaker_cli.db.models import User


@pytest.fixture
def admin_client(tmp_path: Path) -> TestClient:
    client, _ = build_admin_client(
        tmp_path,
        lambda session: session.add(User(id="u-admin", username="admin", role="admin")),
        user_id="u-admin",
        username="admin",
    )
    return client
