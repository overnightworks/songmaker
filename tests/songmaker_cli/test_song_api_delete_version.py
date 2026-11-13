"""Deleting a version answers one body for a missing version and one the caller cannot reach."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.db.models import Album, Song, User, Version

_OWNER_ID = "owner"
_STRANGER_ID = "stranger"


@pytest.fixture
def stranger_client(tmp_path: Path, pg_factory) -> TestClient:
    with pg_factory() as session:
        session.add_all(
            [
                User(id=_OWNER_ID, username="owner", role="user"),
                User(id=_STRANGER_ID, username="stranger", role="user"),
            ]
        )
        session.flush()
        session.add(Album(id="rock", title="Rock", artist="Band", created_by=_OWNER_ID))
        session.add(Song(id="s1", title="Thunder", album_id="rock", track_number=1, slug="thunder"))
        session.add(Version(id="v1", song_id="s1", version_number=1, lyrics="boom"))
        session.commit()
    app = make_router_app(
        make_router_ctx(tmp_path, db=pg_factory),
        user=make_authenticated_user(_STRANGER_ID, username="stranger"),
    )
    return web_client(app)


def test_a_version_of_a_song_the_caller_cannot_reach_answers_like_a_missing_version(
    stranger_client: TestClient,
) -> None:
    missing = stranger_client.delete("/api/versions/no-such-version")
    foreign = stranger_client.delete("/api/versions/v1")

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
