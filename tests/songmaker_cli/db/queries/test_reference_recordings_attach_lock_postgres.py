"""Saving a version's reference link and deleting the reference row serialize on the row."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import Response
from support.postgres_lock_harness import CommitPause, race, wrote_to_tables
from support.web_app import make_test_app, seed_session

from songmaker_cli.constants import REFERENCE_AUDIO_DIR
from songmaker_cli.db.models import Album, ReferenceRecording, Song, User, Version
from songmaker_cli.db.queries.songs import create_song

OWNER = "u1"
REFERENCE_ID = "reference-1"
NOT_FOUND = {"detail": "Not Found"}
IN_USE = {"detail": "Reference audio is in use."}


def _seed(session) -> None:
    session.add(User(id=OWNER, username="owner"))
    session.flush()
    session.add(Album(id="album-a", title="A", artist="A", created_by=OWNER))
    session.add(ReferenceRecording(
        id=REFERENCE_ID, user_id=OWNER, storage_path=f"{OWNER}/{REFERENCE_AUDIO_DIR}/F.wav",
        original_filename="F.wav", size_bytes=4,
    ))
    session.flush()
    create_song(session, "Existing", "album-a", "existing", created_by=OWNER)


class _World:
    """The real routes on PostgreSQL: an owner with one song and one reference row."""

    def __init__(self, pg_factory, tmp_path: Path) -> None:
        self.pg_factory = pg_factory
        self.client, _ = make_test_app(tmp_path, factory=pg_factory, seed_db=_seed)
        seed_session(self.client, "owner")
        with pg_factory() as session:
            self.song_id = session.query(Song).filter_by(slug="existing").one().id

    def attach(self, route: str) -> Response:
        if route == "create":
            return self.client.post("/api/songs", json={
                "title": "Fresh", "album_id": "album-a", "reference_recording_id": REFERENCE_ID,
            })
        return self.client.put(
            f"/api/songs/{self.song_id}", json={"reference_recording_id": REFERENCE_ID},
        )

    def delete_reference(self) -> Response:
        return self.client.delete(f"/api/references/{REFERENCE_ID}")

    def linked_keys(self) -> list[str | None]:
        with self.pg_factory() as session:
            return [version.reference_recording_id for version in session.query(Version)]

    def reference_rows(self) -> int:
        with self.pg_factory() as session:
            return session.query(ReferenceRecording).count()

    def titles(self) -> list[str]:
        with self.pg_factory() as session:
            return sorted(title for (title,) in session.query(Song.title))


@pytest.mark.parametrize("route", ["create", "update"])
def test_a_delete_waits_for_a_save_that_links_the_row_and_then_answers_in_use(
    pg_factory, tmp_path, route,
) -> None:
    world = _World(pg_factory, tmp_path)
    answers = race(pg_factory, lambda: world.attach(route), world.delete_reference)
    assert answers["first"].status_code == 200
    assert answers["second"].status_code == 409
    assert answers["second"].json() == IN_USE
    assert world.reference_rows() == 1
    assert REFERENCE_ID in world.linked_keys()


@pytest.mark.parametrize("route", ["create", "update"])
def test_a_save_waits_for_a_delete_of_the_row_and_then_answers_not_found(
    pg_factory, tmp_path, route,
) -> None:
    world = _World(pg_factory, tmp_path)
    delete_pause = CommitPause(lambda session: wrote_to_tables(session, "reference_recordings"))
    answers = race(
        pg_factory, world.delete_reference, lambda: world.attach(route), delete_pause,
    )
    assert answers["first"].status_code == 204
    assert answers["second"].status_code == 404
    assert answers["second"].json() == NOT_FOUND
    assert world.reference_rows() == 0
    assert world.linked_keys() == [None]
    assert world.titles() == ["Existing"]
