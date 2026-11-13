"""A Refusal answers its sentence and its catalog key; every other error keeps `detail` alone."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from support.web_app import make_router_app, make_router_ctx

from songmaker_cli.refusals import Refusal
from songmaker_cli.words import SOURCE_LANGUAGE, Key, text

GAP_WITH_MARKUP = "<i>{braces}</i> & 'quotes'"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """The router app the tests build, with probe routes that refuse in each way."""
    app: FastAPI = make_router_app(make_router_ctx(tmp_path, db=sessionmaker()))

    @app.get("/probe/archived")
    def archived() -> None:
        raise Refusal(409, "takeRefusal.archived")

    @app.get("/probe/model")
    def model() -> None:
        raise Refusal(400, "modelRefusal.unavailable", model=GAP_WITH_MARKUP)

    @app.get("/probe/headers")
    def headers() -> None:
        refusal = Refusal(409, "takeRefusal.archived")
        refusal.headers = {"Retry-After": "7"}
        raise refusal

    @app.get("/probe/plain")
    def plain() -> None:
        raise HTTPException(409, "Plain sentence")

    return TestClient(app)


def test_a_refusal_answers_its_sentence_and_its_key(client: TestClient) -> None:
    response = client.get("/probe/archived")

    assert response.status_code == 409
    assert response.json() == {
        "detail": text(SOURCE_LANGUAGE, "takeRefusal.archived"),
        "message": {"key": "takeRefusal.archived", "values": {}},
    }


def test_a_refusal_carries_its_gap_values_as_plain_text(client: TestClient) -> None:
    response = client.get("/probe/model")

    assert response.status_code == 400
    assert response.json() == {
        "detail": text(SOURCE_LANGUAGE, "modelRefusal.unavailable", model=GAP_WITH_MARKUP),
        "message": {"key": "modelRefusal.unavailable", "values": {"model": GAP_WITH_MARKUP}},
    }


def test_a_refusal_keeps_the_headers_of_its_exception(client: TestClient) -> None:
    response = client.get("/probe/headers")

    assert response.status_code == 409
    assert response.headers["Retry-After"] == "7"


def test_an_error_that_is_no_refusal_answers_its_detail_alone(client: TestClient) -> None:
    response = client.get("/probe/plain")

    assert response.status_code == 409
    assert response.json() == {"detail": "Plain sentence"}


@pytest.mark.parametrize(
    ("key", "gaps"),
    [
        ("modelRefusal.unavailable", {}),
        ("takeRefusal.archived", {"model": "turbo"}),
    ],
    ids=["missing-gap", "extra-gap"],
)
def test_a_refusal_with_the_wrong_gaps_fails_where_it_is_built(
    key: Key, gaps: dict[str, str]
) -> None:
    with pytest.raises(TypeError):
        Refusal(400, key, **gaps)
