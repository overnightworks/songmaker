"""A Refusal answers its sentence and its catalog key; every other error keeps `detail` alone."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from support.web_app import (
    make_authenticated_user,
    make_router_app,
    make_router_ctx,
    make_test_app,
    refusal_body,
    seed_session,
    seed_user,
)

from songmaker_cli.db.models import Album, AvailableModel, Generation, Song, Version
from songmaker_cli.refusals import Refusal
from songmaker_cli.words import SOURCE_LANGUAGE, Key, text

GAP_WITH_MARKUP = "<i>{braces}</i> & 'quotes'"
OWNER = "owner"


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

    @app.get("/probe/missing")
    def missing() -> None:
        raise Refusal(404, "takeRefusal.archived")

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


def test_a_404_refusal_keeps_its_sentence_and_its_key(client: TestClient) -> None:
    response = client.get("/probe/missing")

    assert response.status_code == 404
    assert response.json() == refusal_body("takeRefusal.archived")


def test_a_path_with_no_route_answers_not_found(client: TestClient) -> None:
    response = client.get("/probe/no-such-route")

    assert (response.status_code, response.json()) == (404, {"detail": "Not Found"})


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


def _seed_song_with_archived_take(session: Session) -> None:
    owner = seed_user(session, OWNER, user_id=OWNER)
    session.add(Album(id="album", title="Album", artist="X", created_by=owner.id))
    session.flush()
    session.add(Song(id="song", title="Song", album_id="album", track_number=1, slug="song"))
    session.flush()
    session.add(Version(id="version", song_id="song", version_number=1, lyrics="l", prompt="p"))
    session.flush()
    session.add(Generation(
        id="take", song_id="song", version_id="version", generation_number=1,
        mp3_path=f"{OWNER}/take.mp3", is_archived=True,
    ))
    session.query(AvailableModel).filter(AvailableModel.id == "sft").update({"is_active": False})


def test_the_live_app_answers_a_refusal_with_its_key_under_the_security_headers(
    tmp_path: Path, pg_factory
) -> None:
    live, _ = make_test_app(tmp_path, seed_db=_seed_song_with_archived_take, factory=pg_factory)
    seed_session(live, OWNER)

    response = live.post("/api/generations/take/pick")

    assert response.status_code == 409
    assert response.json() == refusal_body("takeRefusal.archived")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_the_router_app_answers_the_same_refusal_body_as_the_live_app(
    tmp_path: Path, pg_factory
) -> None:
    ctx = make_router_ctx(tmp_path, db=pg_factory, seed_db=_seed_song_with_archived_take)
    router = TestClient(
        make_router_app(ctx, user=make_authenticated_user(OWNER, username=OWNER))
    )

    response = router.post("/api/generations/take/pick")

    assert response.status_code == 409
    assert response.json() == refusal_body("takeRefusal.archived")


def test_an_inactive_model_is_refused_by_name_with_its_key(tmp_path: Path, pg_factory) -> None:
    ctx = make_router_ctx(tmp_path, db=pg_factory, seed_db=_seed_song_with_archived_take)
    router = TestClient(
        make_router_app(ctx, user=make_authenticated_user(OWNER, username=OWNER))
    )

    response = router.post("/api/songs/song/generate", json={"model": "sft"})

    assert response.status_code == 400
    assert response.json() == refusal_body("modelRefusal.unavailable", model="sft")


def test_the_live_app_keeps_the_sentence_of_an_api_404_and_answers_not_found_for_no_route(
    tmp_path: Path, pg_factory
) -> None:
    live, _ = make_test_app(tmp_path, seed_db=_seed_song_with_archived_take, factory=pg_factory)
    seed_session(live, OWNER)

    @live.app.get("/api/probe/missing")
    def missing() -> None:
        raise Refusal(404, "takeRefusal.archived")

    answers = [
        live.get("/api/probe/missing"),
        live.get("/api/songs/no-such-song"),
        live.get("/api/no-such-route"),
    ]

    assert [(answer.status_code, answer.json()) for answer in answers] == [
        (404, refusal_body("takeRefusal.archived")),
        (404, {"detail": "Song not found"}),
        (404, {"detail": "Not Found"}),
    ]
