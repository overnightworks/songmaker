"""The cover settings endpoint names the providers a save accepts."""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_providers.constants import COWRITER_PROVIDERS
from conftest import (
    make_authenticated_user,
    make_router_app,
    make_router_ctx,
    web_client,
)

from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import User


@pytest.fixture
def admin_client(tmp_path: Path):
    factory = init_db(tmp_path / "cover.db")
    with factory() as session:
        session.add(User(id="u-test", username="u-u-test", role="admin"))
        session.commit()
    app = make_router_app(
        make_router_ctx(tmp_path, db=factory),
        user=make_authenticated_user("u-test", role="admin", username="u-u-test"),
    )
    return web_client(app)


def test_cover_allowed_providers_are_exactly_the_providers_a_save_accepts(admin_client):
    allowed = admin_client.get("/api/settings/cover").json()["allowed_providers"]

    assert allowed == sorted(COWRITER_PROVIDERS)
    for provider in allowed:
        response = admin_client.put(
            "/api/settings/cover", json={"provider": provider, "route": "cli", "model": ""},
        )
        assert response.status_code == 200
        assert response.json()["allowed_providers"] == allowed
