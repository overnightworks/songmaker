"""An album add to a playlist locks its takes in id order, so it waits for a delete, pick or
retention run on the same takes and never deadlocks with it."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

from httpx import Response
from support.postgres_lock_harness import CommitPause, StatementPause, race, wrote_to_tables
from support.web_app import make_test_app, seed_session, seed_user

from songmaker_cli.db.models import Album, Generation, Playlist, PlaylistEntry, Song, Version

OWNER = "owner-1"
PLAYLIST = "playlist-1"
ALBUM_ADD = f"/api/playlists/{PLAYLIST}/entries/album"
RETENTION_RUN = "/api/admin/generation-retention/run"
LONG_AGO = timedelta(days=90)
# The first song's take sorts after the second's, so track order is the reverse of id order.
FIRST_TRACK_TAKE = "z-take"
SECOND_TRACK_TAKE = "a-take"


class _World:
    """The real routes on PostgreSQL: one album of two songs, each with the named takes."""

    def __init__(
        self, pg_factory, tmp_path: Path, takes: dict[str, tuple[str, bool]],
    ) -> None:
        """``takes`` maps a take id to its song id and whether it is old enough to be archived."""
        self.pg_factory = pg_factory

        def seed(session) -> None:
            seed_user(session, "owner", "admin", user_id=OWNER)
            session.flush()
            session.add(Album(id="album-1", title="A", artist="A", created_by=OWNER))
            for track, song_id in enumerate(("song-1", "song-2"), start=1):
                session.add(Song(id=song_id, title=song_id, slug=song_id, album_id="album-1",
                                 track_number=track))
                session.add(Version(id=f"version-{track}", song_id=song_id, version_number=1,
                                    lyrics="", prompt=""))
            session.flush()
            session.add(Playlist(id=PLAYLIST, title="P", slug="p", created_by=OWNER))
            now = datetime.now(timezone.utc)
            session.add_all(
                Generation(
                    id=name, song_id=song_id, version_id=f"version-{song_id[-1]}",
                    generation_number=number, mp3_path=f"album-1/{name}.mp3",
                    created_at=now - LONG_AGO if old else now,
                )
                for number, (name, (song_id, old)) in enumerate(takes.items(), start=1)
            )

        self.client, _ = make_test_app(tmp_path, factory=pg_factory, seed_db=seed)
        seed_session(self.client, "owner")
        for name in takes:
            path = tmp_path / "audio" / "album-1" / f"{name}.mp3"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"mp3")

    def album_add(self) -> Callable[[], Response]:
        return lambda: self.client.post(ALBUM_ADD, json={"album_id": "album-1"})

    def bulk_delete(self, *takes: str) -> Callable[[], Response]:
        return lambda: self.client.post(
            "/api/generations/bulk-delete", json={"generation_ids": list(takes)},
        )

    def pick(self, take: str) -> Callable[[], Response]:
        return lambda: self.client.post(f"/api/generations/{take}/pick")

    def retention(self) -> Callable[[], Response]:
        return lambda: self.client.post(RETENTION_RUN)

    def entries(self) -> list[str]:
        with self.pg_factory() as session:
            return [
                entry.generation_id
                for entry in session.query(PlaylistEntry).order_by(PlaylistEntry.position)
            ]


def _two_songs() -> dict[str, tuple[str, bool]]:
    return {FIRST_TRACK_TAKE: ("song-1", False), SECOND_TRACK_TAKE: ("song-2", False)}


_holding_a_generation_write = partial(
    CommitPause, lambda session: wrote_to_tables(session, "generations"),
)


def _after_the_take_locks(statement: str) -> bool:
    return "FROM generations" in statement and "FOR UPDATE" in statement


def test_an_album_add_holding_its_take_locks_leaves_a_bulk_delete_of_them_waiting_not_deadlocked(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path, _two_songs())
    answers = race(
        pg_factory, world.album_add(),
        world.bulk_delete(FIRST_TRACK_TAKE, SECOND_TRACK_TAKE),
        StatementPause(_after_the_take_locks),
    )
    assert answers["first"].status_code == 200
    assert answers["first"].json()["added_count"] == 2
    assert answers["second"].status_code == 200
    assert world.entries() == []


def test_an_album_add_waits_for_a_bulk_delete_of_both_takes_and_skips_their_songs(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path, _two_songs())
    answers = race(
        pg_factory, world.bulk_delete(FIRST_TRACK_TAKE, SECOND_TRACK_TAKE), world.album_add(),
        _holding_a_generation_write(),
    )
    assert answers["first"].status_code == 200
    assert answers["second"].status_code == 200
    body = answers["second"].json()
    assert body["added_count"] == 0
    assert [(skip["song_id"], skip["reason"]) for skip in body["skipped"]] == [
        ("song-1", "no_playable_take"), ("song-2", "no_playable_take"),
    ]
    assert world.entries() == []


def test_an_album_add_waits_for_a_delete_of_one_take_and_adds_the_other(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path, _two_songs())
    answers = race(
        pg_factory, world.bulk_delete(SECOND_TRACK_TAKE), world.album_add(),
        _holding_a_generation_write(),
    )
    assert answers["second"].status_code == 200
    body = answers["second"].json()
    assert body["added_count"] == 1
    assert [(skip["song_id"], skip["reason"]) for skip in body["skipped"]] == [
        ("song-2", "no_playable_take"),
    ]
    assert world.entries() == [FIRST_TRACK_TAKE]


def test_an_album_add_holding_its_take_locks_leaves_a_pick_in_the_album_waiting(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path, {
        "z-sibling": ("song-1", True), FIRST_TRACK_TAKE: ("song-1", False),
        SECOND_TRACK_TAKE: ("song-2", False),
    })
    answers = race(
        pg_factory, world.album_add(), world.pick("z-sibling"),
        StatementPause(_after_the_take_locks),
    )
    assert answers["first"].status_code == 200
    assert answers["first"].json()["added_count"] == 2
    assert answers["second"].status_code == 200


def test_an_album_add_waits_for_the_archive_of_a_take_and_adds_the_others(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path, {
        FIRST_TRACK_TAKE: ("song-1", True), SECOND_TRACK_TAKE: ("song-2", False),
    })
    answers = race(
        pg_factory, world.retention(), world.album_add(), _holding_a_generation_write(),
    )
    assert answers["first"].json()["archived_ids"] == [FIRST_TRACK_TAKE]
    assert answers["second"].status_code == 200
    body = answers["second"].json()
    assert body["added_count"] == 1
    assert [(skip["song_id"], skip["reason"]) for skip in body["skipped"]] == [
        ("song-1", "no_playable_take"),
    ]
    assert world.entries() == [SECOND_TRACK_TAKE]


def test_an_album_add_without_a_race_adds_the_takes_in_track_order(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path, _two_songs())
    response = world.album_add()()
    assert response.status_code == 200
    assert response.json()["added_count"] == 2
    assert response.json()["skipped"] == []
    assert world.entries() == [FIRST_TRACK_TAKE, SECOND_TRACK_TAKE]
