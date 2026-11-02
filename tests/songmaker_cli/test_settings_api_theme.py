"""The theme endpoint stores one three-way choice per person."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import User

THEME_URL = "/api/settings/theme"


@pytest.fixture
def two_people(tmp_path) -> tuple[TestClient, TestClient]:
    def seed(session) -> None:
        session.add_all([User(id="u-ana", username="ana"), User(id="u-ben", username="ben")])

    ctx = make_router_ctx(tmp_path, db=init_test_db(tmp_path / "theme.db"), seed_db=seed)
    return tuple(
        web_client(make_router_app(ctx, user=make_authenticated_user(user_id)))
        for user_id in ("u-ana", "u-ben")
    )


@pytest.fixture
def anonymous_client(tmp_path) -> TestClient:
    return web_client(make_router_app(make_router_ctx(tmp_path)))


def test_a_new_person_follows_the_device(two_people):
    ana, _ = two_people
    assert ana.get(THEME_URL).json() == {"theme": "system"}


@pytest.mark.parametrize("theme", ["light", "dark", "system"])
def test_each_theme_round_trips(two_people, theme):
    ana, _ = two_people
    assert ana.put(THEME_URL, json={"theme": theme}).json() == {"theme": theme}
    assert ana.get(THEME_URL).json() == {"theme": theme}


def test_one_persons_choice_leaves_another_persons_unchanged(two_people):
    ana, ben = two_people
    ana.put(THEME_URL, json={"theme": "dark"})
    assert ben.get(THEME_URL).json() == {"theme": "system"}


@pytest.mark.parametrize(
    "body", [{"theme": "auto"}, {"theme": "follow-system"}, {"theme": None}, {}],
)
def test_a_value_outside_the_three_ways_is_refused_and_the_choice_stays(two_people, body):
    ana, _ = two_people
    ana.put(THEME_URL, json={"theme": "dark"})
    assert ana.put(THEME_URL, json=body).status_code == 422
    assert ana.get(THEME_URL).json() == {"theme": "dark"}


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_without_a_session_the_theme_endpoint_answers_401(anonymous_client, method):
    response = anonymous_client.request(method, THEME_URL, json={"theme": "dark"})
    assert response.status_code == 401
