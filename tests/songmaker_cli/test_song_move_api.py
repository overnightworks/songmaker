"""The move route keeps a person's songs within their own albums, as the last track."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Song, User

_OWNER_ID = "owner"
_STRANGER_ID = "stranger"


@pytest.fixture
def make_client(tmp_path: Path):
    factory = init_test_db(tmp_path / "test.db")
    with factory() as session:
        for user_id in (_OWNER_ID, _STRANGER_ID):
            session.add(User(id=user_id, username=user_id, role="user"))
        session.flush()
        session.add(Album(id="mine", title="Mine", artist="Band", created_by=_OWNER_ID))
        session.add(Album(id="mine-too", title="Mine Too", artist="Band", created_by=_OWNER_ID))
        session.add(Album(id="theirs", title="Theirs", artist="Band", created_by=_STRANGER_ID))
        session.add(Song(id="own-song", title="Own", album_id="mine", track_number=1, slug="own"))
        session.add(
            Song(id="their-song", title="Their", album_id="theirs", track_number=1, slug="their"),
        )
        for number in (1, 2, 3):
            session.add(
                Song(
                    id=f"t{number}",
                    title=f"Track {number}",
                    album_id="mine-too",
                    track_number=number,
                    slug=f"track-{number}",
                ),
            )
        session.commit()
    ctx = make_router_ctx(tmp_path, db=factory)

    def open_as(user_id: str, *, role: str = "user") -> TestClient:
        user = make_authenticated_user(user_id, role=role)
        return web_client(make_router_app(ctx, user=user))

    return open_as


def test_the_owner_moves_their_song_to_the_last_track_of_their_other_album(make_client) -> None:
    client = make_client(_OWNER_ID)

    resp = client.put("/api/songs/own-song/album", json={"album_id": "mine-too"})

    assert (resp.status_code, resp.json()["album_id"], resp.json()["track_number"]) == (
        200,
        "mine-too",
        4,
    )


@pytest.mark.parametrize("role", ["user", "admin"])
@pytest.mark.parametrize(
    ("actor_id", "song_id", "album_id", "detail"),
    [
        (_STRANGER_ID, "own-song", "mine-too", "Song not found"),
        (_OWNER_ID, "own-song", "theirs", "Album not found"),
    ],
    ids=["another-persons-song", "another-persons-album"],
)
def test_a_move_across_owners_answers_not_found_even_for_an_admin(
    make_client,
    role: str,
    actor_id: str,
    song_id: str,
    album_id: str,
    detail: str,
) -> None:
    client = make_client(actor_id, role=role)

    resp = client.put(f"/api/songs/{song_id}/album", json={"album_id": album_id})

    assert (resp.status_code, resp.json()["detail"]) == (404, detail)
