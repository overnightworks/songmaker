"""The theme endpoint stores one three-way choice per person."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from support.signed_in_people import sign_in_people
from support.web_app import make_router_app, make_router_ctx, web_client

THEME_URL = "/api/settings/theme"


@pytest.fixture
def two_people(tmp_path, pg_factory) -> tuple[TestClient, TestClient]:
    clients = sign_in_people(tmp_path, pg_factory, {"ana": "user", "ben": "user"})
    return clients["ana"], clients["ben"]


@pytest.fixture
def anonymous_client(tmp_path, pg_factory) -> TestClient:
    return web_client(make_router_app(make_router_ctx(tmp_path, db=pg_factory)))


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
