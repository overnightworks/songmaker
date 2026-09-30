"""A person's own work on a song: the edits they save and the listens they start.

Anyone who can open a song leaves a record of their own, whoever owns it. The
song's global ``last_played_at`` stays the owner's alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from conftest import make_authenticated_user, make_router_app, make_router_ctx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Generation, Song, User, UserSongWork, Version
from songmaker_cli.db.queries import SongWork, record_song_work

OWNER_ID = "u-owner"
ADMIN_ID = "u-admin"
SONG_ID = "s1"

EDITS = {
    "update": ("put", f"/api/songs/{SONG_ID}", {"lyrics": "new words"}),
    "rename": ("put", f"/api/songs/{SONG_ID}/title", {"title": "New Title"}),
}
LISTEN = ("post", f"/api/songs/{SONG_ID}/listen", None)


def _seed(session: Session) -> None:
    session.add_all([
        User(id=OWNER_ID, username="leonardo", password_hash="unused", role="user"),
        User(id=ADMIN_ID, username="felix", password_hash="unused", role="admin"),
    ])
    session.flush()
    session.add(Album(id="alb", title="Album", artist="Leonardo", created_by=OWNER_ID))
    session.add(Song(id=SONG_ID, title="Thunder", album_id="alb", track_number=1, slug="thunder"))
    session.add(Version(id="v1", song_id=SONG_ID, version_number=1, lyrics="boom"))
    session.add(Generation(
        id="g1", song_id=SONG_ID, version_id="v1", generation_number=1,
        mp3_path=f"{OWNER_ID}/g1.mp3", seed=1,
    ))


@pytest.fixture
def db(tmp_path: Path) -> sessionmaker[Session]:
    return make_router_ctx(tmp_path, db=init_test_db(tmp_path / "work.db"), seed_db=_seed).db


def _client(tmp_path: Path, db: sessionmaker[Session], *, user_id: str, role: str) -> TestClient:
    app = make_router_app(
        make_router_ctx(tmp_path, db=db),
        user=make_authenticated_user(user_id, role=role),
    )
    return TestClient(app)


def _send(client: TestClient, request: tuple[str, str, dict | None]):
    method, url, body = request
    return client.request(method.upper(), url, json=body)


def _work_rows(
    db: sessionmaker[Session], song_id: str = SONG_ID,
) -> dict[str, tuple[bool, bool]]:
    """Each person's row on the song as (has an edit, has a listen)."""
    with db() as session:
        return {
            row.user_id: (row.edited_at is not None, row.played_at is not None)
            for row in session.query(UserSongWork).filter_by(song_id=song_id)
        }


def _song_last_played(db: sessionmaker[Session]) -> datetime | None:
    with db() as session:
        return session.get(Song, SONG_ID).last_played_at


@pytest.mark.parametrize(("user_id", "role"), [(ADMIN_ID, "admin"), (OWNER_ID, "user")])
@pytest.mark.parametrize("edit", sorted(EDITS))
def test_saving_an_edit_records_the_editors_own_work(
    tmp_path: Path, db, user_id: str, role: str, edit: str,
) -> None:
    client = _client(tmp_path, db, user_id=user_id, role=role)

    assert _send(client, EDITS[edit]).status_code == 200

    assert _work_rows(db) == {user_id: (True, False)}
    assert _song_last_played(db) is None


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
    assert _work_rows(db, resp.json()["id"]) == {user_id: (True, False)}


def test_an_admin_listen_on_a_foreign_song_records_only_the_admins_work(
    tmp_path: Path, db,
) -> None:
    client = _client(tmp_path, db, user_id=ADMIN_ID, role="admin")

    assert _send(client, LISTEN).status_code == 200

    assert _work_rows(db) == {ADMIN_ID: (False, True)}
    assert _song_last_played(db) is None


def test_an_owner_listen_marks_the_song_and_records_the_owners_work(
    tmp_path: Path, db,
) -> None:
    client = _client(tmp_path, db, user_id=OWNER_ID, role="user")

    assert _send(client, LISTEN).status_code == 200

    assert _work_rows(db) == {OWNER_ID: (False, True)}
    assert _song_last_played(db) is not None


def test_a_rejected_listen_records_no_work(tmp_path: Path, db) -> None:
    with db() as session:
        session.get(Generation, "g1").mp3_path = ""
        session.commit()
    client = _client(tmp_path, db, user_id=ADMIN_ID, role="admin")

    assert _send(client, LISTEN).status_code == 422

    assert _work_rows(db) == {}


def test_a_person_who_cannot_open_the_song_records_no_work(tmp_path: Path, db) -> None:
    with db() as session:
        session.add(User(id="u-stranger", username="bob", password_hash="unused", role="user"))
        session.commit()
    client = _client(tmp_path, db, user_id="u-stranger", role="user")

    for request in (*EDITS.values(), LISTEN):
        assert _send(client, request).status_code == 404

    assert _work_rows(db) == {}


def test_repeated_work_keeps_one_row_that_holds_the_latest_of_each_kind(db) -> None:
    with db() as session:
        record_song_work(session, user_id=ADMIN_ID, song_id=SONG_ID, work=SongWork.PLAYED)
        record_song_work(session, user_id=ADMIN_ID, song_id=SONG_ID, work=SongWork.EDITED)
        session.commit()
        first_edited = session.get(UserSongWork, (ADMIN_ID, SONG_ID)).edited_at

    before_replay = datetime.now(timezone.utc)
    with db() as session:
        record_song_work(session, user_id=ADMIN_ID, song_id=SONG_ID, work=SongWork.PLAYED)
        session.commit()

    with db() as session:
        rows = session.query(UserSongWork).all()
        assert len(rows) == 1
        assert rows[0].edited_at == first_edited
        assert rows[0].played_at.replace(tzinfo=timezone.utc) >= before_replay


@pytest.mark.parametrize(("model", "key"), [(Song, SONG_ID), (User, ADMIN_ID)])
def test_removing_the_song_or_the_person_removes_their_work(db, model, key: str) -> None:
    with db() as session:
        record_song_work(session, user_id=ADMIN_ID, song_id=SONG_ID, work=SongWork.EDITED)
        session.commit()

    with db() as session:
        session.delete(session.get(model, key))
        session.commit()

    assert _work_rows(db) == {}
