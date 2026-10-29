"""A client signed in as an admin on a fresh test database."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_authenticated_user, make_router_app, make_router_ctx, web_client
from fastapi.testclient import TestClient

from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import User


@pytest.fixture
def admin_client(tmp_path: Path) -> TestClient:
    factory = init_test_db(tmp_path / "admin.db")
    with factory() as session:
        session.add(User(id="u-admin", username="admin", role="admin"))
        session.commit()
    app = make_router_app(
        make_router_ctx(tmp_path, db=factory),
        user=make_authenticated_user("u-admin", role="admin", username="admin"),
    )
    return web_client(app)
