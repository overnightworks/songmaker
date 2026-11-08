"""The web API stores a stripped title that fits the column and refuses any other untouched."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.db.models import Album, AuditLog, Song, User, Version

_OWNER_ID = "owner"
_TITLE_LENGTH = Song.__table__.c.title.type.length

WRITES = pytest.mark.parametrize(
    ("method", "path", "body"),
    [("POST", "/api/songs", {"album_id": "rock"}), ("PUT", "/api/songs/s1/title", {})],
    ids=["create", "rename"],
)


@pytest.fixture
def client(tmp_path: Path, pg_factory) -> TestClient:
    with pg_factory() as session:
        session.add(User(id=_OWNER_ID, username="owner", role="user"))
        session.flush()
        session.add(Album(id="rock", title="Rock", artist="Band", created_by=_OWNER_ID))
        session.add(Song(id="s1", title="Thunder", album_id="rock", track_number=1, slug="thunder"))
        session.add(Version(id="v1", song_id="s1", version_number=1, lyrics="boom"))
        session.commit()
    app = make_router_app(
        make_router_ctx(tmp_path, db=pg_factory),
        user=make_authenticated_user(_OWNER_ID, username="owner"),
    )
    return web_client(app)


def _stored_rows(client: TestClient) -> tuple[list, list]:
    with client.app.state.ctx.db() as session:
        songs = session.query(Song.id, Song.title, Song.slug).all()
        return songs, session.query(AuditLog.id).all()


@WRITES
@pytest.mark.parametrize(
    ("title", "stored"),
    [("  Night Drive ", "Night Drive"), ("x" * _TITLE_LENGTH, "x" * _TITLE_LENGTH)],
    ids=["padded", "longest"],
)
def test_song_write_stores_the_stripped_title(client, method, path, body, title, stored) -> None:
    resp = client.request(method, path, json={**body, "title": title})

    with client.app.state.ctx.db() as session:
        persisted = session.get(Song, resp.json()["id"]).title
    assert (resp.status_code, resp.json()["title"], persisted) == (200, stored, stored)


@WRITES
@pytest.mark.parametrize(
    "title", ["", "   ", "x" * (_TITLE_LENGTH + 1)], ids=["empty", "blank", "too-long"],
)
def test_song_write_refuses_an_unstorable_title_before_any_write(
    client, method, path, body, title,
) -> None:
    before = _stored_rows(client)

    resp = client.request(method, path, json={**body, "title": title})

    assert (resp.status_code, _stored_rows(client)) == (422, before)
