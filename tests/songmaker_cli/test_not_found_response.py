"""A 404 on the API keeps what its route raised, in the live app and in the router test app."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from support.web_app import make_test_app, refusal_body, seed_session, web_client

from songmaker_cli.db.models import User
from songmaker_cli.refusals import Refusal, install_refusal_handler

_REFUSAL_KEY = "cowriterRefusal.browserLogin"


def _add_refusing_route(app: FastAPI) -> None:
    @app.get("/api/refuses-with-not-found")
    def refuses_with_not_found() -> None:
        raise Refusal(404, _REFUSAL_KEY)


@pytest.fixture(params=["router-app", "live-app"])
def client(request: pytest.FixtureRequest, tmp_path: Path, pg_factory) -> TestClient:
    if request.param == "router-app":
        app = FastAPI()
        install_refusal_handler(app)
        _add_refusing_route(app)
        return web_client(app)

    def seed_member(session) -> None:
        session.add(User(id="member", username="member", role="user"))

    live_client, _ = make_test_app(tmp_path, seed_db=seed_member, factory=pg_factory)
    seed_session(live_client, "member")
    _add_refusing_route(live_client.app)
    return live_client


def test_a_404_refusal_keeps_its_message(client: TestClient) -> None:
    response = client.get("/api/refuses-with-not-found")

    assert (response.status_code, response.json()) == (404, refusal_body(_REFUSAL_KEY))


def test_a_path_with_no_route_answers_not_found(client: TestClient) -> None:
    response = client.get("/api/no-such-route")

    assert (response.status_code, response.json()) == (404, {"detail": "Not Found"})
