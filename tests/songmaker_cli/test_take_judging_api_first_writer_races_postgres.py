"""Two writers at the same moment each get their declared answer: a take's mark or rating
behind a delete, a first rating, a first memory write and a share toggle."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest
from httpx import Response
from support.postgres_lock_harness import CommitPause, race, wrote_to_tables
from support.web_app import make_test_app, seed_session, seed_user

from songmaker_cli.db.models import (
    Album,
    CowriterAlbumMemory,
    CowriterSongMemory,
    CowriterUserMemory,
    Generation,
    Rating,
    Song,
    Version,
)

OWNER = "owner-1"
SONG = "song-1"
ALBUM = "album-1"
TAKE = "take-1"
EARLIER_LINK = "earlier-link"


class _World:
    """The real routes on PostgreSQL: one album, one song and one take of the owner."""

    def __init__(self, pg_factory, tmp_path: Path, *, song_shared: bool = False) -> None:
        self.pg_factory = pg_factory

        def seed(session) -> None:
            seed_user(session, "owner", "admin", user_id=OWNER)
            session.flush()
            session.add(Album(id=ALBUM, title="A", artist="A", created_by=OWNER))
            session.add(Song(
                id=SONG, title=SONG, slug=SONG, album_id=ALBUM, track_number=1,
                is_shared=song_shared, share_slug=EARLIER_LINK if song_shared else None,
            ))
            session.add(Version(
                id="version-1", song_id=SONG, version_number=1, lyrics="", prompt="",
            ))
            session.flush()
            session.add(Generation(
                id=TAKE, song_id=SONG, version_id="version-1", generation_number=1,
                mp3_path="album-1/take-1.mp3", is_picked=True, is_kept=True, is_archived=True,
            ))

        self.client, _ = make_test_app(tmp_path, factory=pg_factory, seed_db=seed)
        seed_session(self.client, "owner")

    def post(self, path: str, **body) -> Callable[[], Response]:
        return lambda: self.client.post(path, **body)

    def put(self, path: str, body: str) -> Callable[[], Response]:
        return lambda: self.client.put(path, json={"body": body})

    def delete(self, path: str) -> Callable[[], Response]:
        return lambda: self.client.delete(path)

    def delete_take(self) -> Callable[[], Response]:
        return self.post("/api/generations/bulk-delete", json={"generation_ids": [TAKE]})

    def rate(self, rating: float) -> Callable[[], Response]:
        return self.post(f"/api/generations/{TAKE}/rate", json={"rating": rating})

    def rows(self, model) -> list:
        with self.pg_factory() as session:
            return session.query(model).all()

    def song(self) -> Song:
        with self.pg_factory() as session:
            return session.get(Song, SONG)


def _holding_a_write_to(*tables: str) -> CommitPause:
    return CommitPause(lambda session: wrote_to_tables(session, *tables))


@pytest.mark.parametrize("action", ["unpick", "unkeep", "unarchive"])
def test_a_mark_behind_a_delete_of_the_take_answers_not_found(
    pg_factory, tmp_path, action,
) -> None:
    world = _World(pg_factory, tmp_path)
    answers = race(
        pg_factory, world.delete_take(), world.post(f"/api/generations/{TAKE}/{action}"),
        _holding_a_write_to("generations"),
    )
    assert answers["first"].status_code == 200
    assert answers["second"].status_code == 404
    assert world.rows(Generation) == []


def test_a_rating_behind_a_delete_of_the_take_answers_not_found(pg_factory, tmp_path) -> None:
    world = _World(pg_factory, tmp_path)
    answers = race(
        pg_factory, world.delete_take(), world.rate(4.0), _holding_a_write_to("generations"),
    )
    assert answers["second"].status_code == 404
    assert world.rows(Rating) == []


def test_two_first_ratings_of_one_take_both_answer_and_the_later_value_stays(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    answers = race(
        pg_factory, world.rate(2.0), world.rate(5.0), _holding_a_write_to("ratings"),
    )
    assert answers["first"].status_code == 200
    assert answers["second"].status_code == 200
    assert [rating.rating for rating in world.rows(Rating)] == [5.0]


@pytest.mark.parametrize(("path", "table", "model"), [
    ("/api/memory/user", "cowriter_user_memories", CowriterUserMemory),
    (f"/api/memory/songs/{SONG}", "cowriter_song_memories", CowriterSongMemory),
    (f"/api/memory/albums/{ALBUM}", "cowriter_album_memories", CowriterAlbumMemory),
])
def test_two_first_writes_of_one_note_both_answer_and_the_later_body_stays(
    pg_factory, tmp_path, path, table, model,
) -> None:
    world = _World(pg_factory, tmp_path)
    answers = race(
        pg_factory, world.put(path, "earlier"), world.put(path, "later"),
        _holding_a_write_to(table),
    )
    assert answers["first"].status_code == 200
    assert answers["second"].status_code == 200
    assert answers["second"].json()["body"] == "later"
    assert [note.body for note in world.rows(model)] == ["later"]


def test_two_enables_of_one_song_both_name_the_stored_link(pg_factory, tmp_path) -> None:
    world = _World(pg_factory, tmp_path)
    enable = partial(world.post, f"/api/songs/{SONG}/share")
    answers = race(pg_factory, enable(), enable(), _holding_a_write_to("songs"))
    stored = world.song().share_slug
    assert answers["first"].json()["share_slug"] == stored
    assert answers["second"].json()["share_slug"] == stored


def test_an_enable_behind_a_disable_makes_a_new_link_and_the_old_one_stays_dead(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path, song_shared=True)
    answers = race(
        pg_factory, world.delete(f"/api/songs/{SONG}/share"),
        world.post(f"/api/songs/{SONG}/share"), _holding_a_write_to("songs"),
    )
    song = world.song()
    assert answers["second"].status_code == 200
    assert song.is_shared
    assert song.share_slug != EARLIER_LINK
    assert answers["second"].json()["share_slug"] == song.share_slug
