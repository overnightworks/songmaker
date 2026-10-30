"""A person's own work on a song: the edits they save and the listens they start.

Anyone who can open a song leaves a record of their own, whoever owns it. An
edit records its kind; a listen outside a playlist is an album listen too. A
listen leaves the song itself unmarked, whoever starts it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.constants import SongWorkKind
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import (
    Album,
    Generation,
    Playlist,
    PlaylistEntry,
    Song,
    User,
    UserSongWork,
    Version,
)
from songmaker_cli.db.queries.activity import record_song_edit, record_song_played

OWNER_ID = "u-owner"
ADMIN_ID = "u-admin"
SONG_ID = "s1"
PLAYLIST_ID = "p-own"
SONG_URL = f"/api/songs/{SONG_ID}"
LYRICS_EDIT = ("put", SONG_URL, {"lyrics": "new words"})
RENAME = ("put", f"{SONG_URL}/title", {"title": "New Title"})

EDITS = {
    "lyrics": (LYRICS_EDIT, SongWorkKind.LYRICS),
    "prompt": (("put", SONG_URL, {"prompt": "dark synthwave"}), SongWorkKind.STYLE),
    "bpm": (("put", SONG_URL, {"bpm": 90}), SongWorkKind.STYLE),
    "key": (("put", SONG_URL, {"key_scale": "A minor"}), SongWorkKind.STYLE),
    "duration": (("put", SONG_URL, {"audio_duration": 120}), SongWorkKind.STYLE),
    "language": (("put", SONG_URL, {"vocal_language": "de"}), SongWorkKind.STYLE),
    "generation-param": (
        ("put", SONG_URL, {"generation_params": {"inference_steps": 25}}), SongWorkKind.STYLE,
    ),
    "lyrics-and-style": (
        ("put", SONG_URL, {"lyrics": "new words", "prompt": "dark synthwave", "bpm": 90}),
        SongWorkKind.LYRICS,
    ),
    "rename": (RENAME, SongWorkKind.RENAMED),
}
LISTEN_URL = f"{SONG_URL}/listen"
LISTEN = ("post", LISTEN_URL, None)


class Work(NamedTuple):
    """A person's row on the song, as the facts it holds."""

    edited: bool = False
    kind: str | None = None
    played: bool = False
    album_played: bool = False


def _seed(session: Session) -> None:
    session.add_all([
        User(id=OWNER_ID, username="leonardo", role="user"),
        User(id=ADMIN_ID, username="felix", role="admin"),
    ])
    session.flush()
    session.add(Album(id="alb", title="Album", artist="Leonardo", created_by=OWNER_ID))
    session.add(Song(id=SONG_ID, title="Thunder", album_id="alb", track_number=1, slug="thunder"))
    session.add(Version(id="v1", song_id=SONG_ID, version_number=1, lyrics="boom"))
    session.add(Generation(
        id="g1", song_id=SONG_ID, version_id="v1", generation_number=1,
        mp3_path=f"{OWNER_ID}/g1.mp3", seed=1,
    ))
    session.add(Playlist(
        id=PLAYLIST_ID, title="Night Drive", slug="night-drive", created_by=OWNER_ID,
    ))
    session.flush()
    session.add(PlaylistEntry(playlist_id=PLAYLIST_ID, generation_id="g1", position=0))


@pytest.fixture
def db(tmp_path: Path) -> sessionmaker[Session]:
    return make_router_ctx(tmp_path, db=init_test_db(tmp_path / "work.db"), seed_db=_seed).db


def _client(tmp_path: Path, db: sessionmaker[Session], *, user_id: str, role: str) -> TestClient:
    app = make_router_app(
        make_router_ctx(tmp_path, db=db),
        user=make_authenticated_user(user_id, role=role),
    )
    return web_client(app)


def _send(client: TestClient, request: tuple[str, str, dict | None]):
    method, url, body = request
    return client.request(method.upper(), url, json=body)


def _work_rows(db: sessionmaker[Session], song_id: str = SONG_ID) -> dict[str, Work]:
    with db() as session:
        return {
            row.user_id: Work(
                edited=row.edited_at is not None,
                kind=row.edit_kind,
                played=row.played_at is not None,
                album_played=row.album_played_at is not None,
            )
            for row in session.query(UserSongWork).filter_by(song_id=song_id)
        }


@pytest.mark.parametrize(("user_id", "role"), [(ADMIN_ID, "admin"), (OWNER_ID, "user")])
@pytest.mark.parametrize("edit", sorted(EDITS))
def test_saving_an_edit_records_the_editors_own_work_and_its_kind(
    tmp_path: Path, db, user_id: str, role: str, edit: str,
) -> None:
    request, kind = EDITS[edit]
    client = _client(tmp_path, db, user_id=user_id, role=role)

    assert _send(client, request).status_code == 200

    assert _work_rows(db) == {user_id: Work(edited=True, kind=kind)}


def test_the_latest_edit_names_the_kind_of_the_editors_work(tmp_path: Path, db) -> None:
    client = _client(tmp_path, db, user_id=OWNER_ID, role="user")

    for request in (LYRICS_EDIT, RENAME):
        assert _send(client, request).status_code == 200

    assert _work_rows(db) == {OWNER_ID: Work(edited=True, kind=SongWorkKind.RENAMED)}


@pytest.mark.parametrize("edit", ["lyrics", "prompt"])
def test_a_save_on_a_song_without_a_version_records_the_kind_it_changed(
    tmp_path: Path, db, edit: str,
) -> None:
    request, kind = EDITS[edit]
    client = _client(tmp_path, db, user_id=OWNER_ID, role="user")
    assert client.delete("/api/versions/v1").status_code == 200

    assert _send(client, request).status_code == 200

    assert _work_rows(db) == {OWNER_ID: Work(edited=True, kind=kind)}


@pytest.mark.parametrize(
    "save",
    [
        ("put", f"/api/songs/{SONG_ID}", {}),
        ("put", f"/api/songs/{SONG_ID}", {"lyrics": "boom"}),
        ("put", f"/api/songs/{SONG_ID}/title", {"title": "Thunder"}),
    ],
    ids=["empty-update", "unchanged-lyrics", "unchanged-title"],
)
def test_a_save_that_changes_nothing_records_no_work(
    tmp_path: Path, db, save: tuple[str, str, dict],
) -> None:
    client = _client(tmp_path, db, user_id=ADMIN_ID, role="admin")

    assert _send(client, save).status_code == 200

    assert _work_rows(db) == {}


@pytest.mark.parametrize(("user_id", "role"), [(ADMIN_ID, "admin"), (OWNER_ID, "user")])
def test_creating_a_song_records_the_creators_own_work(
    tmp_path: Path, db, user_id: str, role: str,
) -> None:
    client = _client(tmp_path, db, user_id=user_id, role=role)

    resp = client.post("/api/songs", json={"album_id": "alb", "title": "Fresh"})

    assert resp.status_code == 200, resp.text
    assert _work_rows(db, resp.json()["id"]) == {
        user_id: Work(edited=True, kind=SongWorkKind.CREATED),
    }


@pytest.mark.parametrize(("user_id", "role"), [(ADMIN_ID, "admin"), (OWNER_ID, "user")])
def test_a_listen_records_only_the_listeners_own_work_and_leaves_the_song_unmarked(
    tmp_path: Path, db, user_id: str, role: str,
) -> None:
    client = _client(tmp_path, db, user_id=user_id, role=role)

    assert _send(client, LISTEN).status_code == 200

    assert _work_rows(db) == {user_id: Work(played=True, album_played=True)}
    with db() as session:
        assert session.get(Song, SONG_ID).last_played_at is None


@pytest.mark.parametrize(
    ("body", "album_played"),
    [(None, True), ({"playlist_id": None}, True), ({"playlist_id": PLAYLIST_ID}, False)],
    ids=["album-or-library-shuffle", "no-playlist-named", "inside-a-playlist"],
)
def test_only_a_listen_outside_a_playlist_counts_as_an_album_listen(
    tmp_path: Path, db, body: dict | None, album_played: bool,
) -> None:
    client = _client(tmp_path, db, user_id=OWNER_ID, role="user")

    assert client.post(LISTEN_URL, json=body).status_code == 200

    assert _work_rows(db) == {OWNER_ID: Work(played=True, album_played=album_played)}


@pytest.mark.parametrize(
    ("playable", "body", "status"),
    [(False, None, 422), (True, {"playlist_id": PLAYLIST_ID}, 404)],
    ids=["no-playable-take", "another-musicians-playlist"],
)
def test_a_rejected_listen_records_no_work(
    tmp_path: Path, db, playable: bool, body: dict | None, status: int,
) -> None:
    if not playable:
        with db() as session:
            session.get(Generation, "g1").mp3_path = ""
            session.commit()
    client = _client(tmp_path, db, user_id=ADMIN_ID, role="admin")

    assert client.post(LISTEN_URL, json=body).status_code == status

    assert _work_rows(db) == {}


def test_a_person_who_cannot_open_the_song_records_no_work(tmp_path: Path, db) -> None:
    with db() as session:
        session.add(User(id="u-stranger", username="bob", role="user"))
        session.commit()
    client = _client(tmp_path, db, user_id="u-stranger", role="user")

    for request in (*(request for request, _ in EDITS.values()), LISTEN):
        assert _send(client, request).status_code == 404

    assert _work_rows(db) == {}


def test_repeated_work_keeps_one_row_that_holds_the_latest_of_each_kind(db) -> None:
    with db() as session:
        record_song_played(session, user_id=ADMIN_ID, song_id=SONG_ID, in_playlist=False)
        record_song_edit(session, user_id=ADMIN_ID, song_id=SONG_ID, kind=SongWorkKind.LYRICS)
        session.commit()
        first = session.get(UserSongWork, (ADMIN_ID, SONG_ID))
        first_edited, first_album_played = first.edited_at, first.album_played_at

    before_replay = datetime.now(timezone.utc)
    with db() as session:
        record_song_played(session, user_id=ADMIN_ID, song_id=SONG_ID, in_playlist=True)
        session.commit()

    with db() as session:
        rows = session.query(UserSongWork).all()
        assert len(rows) == 1
        assert rows[0].edited_at == first_edited
        assert rows[0].edit_kind == SongWorkKind.LYRICS
        assert rows[0].album_played_at == first_album_played
        assert rows[0].played_at.replace(tzinfo=timezone.utc) >= before_replay


@pytest.mark.parametrize(("model", "key"), [(Song, SONG_ID), (User, ADMIN_ID)])
def test_removing_the_song_or_the_person_removes_their_work(db, model, key: str) -> None:
    with db() as session:
        record_song_edit(session, user_id=ADMIN_ID, song_id=SONG_ID, kind=SongWorkKind.LYRICS)
        session.commit()

    with db() as session:
        session.delete(session.get(model, key))
        session.commit()

    assert _work_rows(db) == {}
