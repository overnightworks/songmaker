"""Writers of one playlist's order wait for each other, so its positions stay 0 to n-1."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from httpx import Response
from support.postgres_lock_harness import StatementPause, after_the_playlist_lock, race
from support.web_app import make_test_app, seed_session, seed_user

from songmaker_cli.db.models import Album, Generation, Playlist, PlaylistEntry, Song, Version

OWNER = "owner-1"
TARGET = "target"
TAKES = ("take-1", "take-2", "take-3", "take-4", "take-5", "take-6", "take-7")
FIRST_SOURCE = ("take-1", "take-2", "take-3")
SECOND_SOURCE = ("take-4", "take-5", "take-6")


class _World:
    """The real routes on PostgreSQL: seven takes with audio, an empty target and two
    playlists of three takes each."""

    def __init__(self, pg_factory, tmp_path: Path) -> None:
        self.pg_factory = pg_factory

        def seed(session) -> None:
            seed_user(session, "owner", user_id=OWNER)
            session.flush()
            session.add(Album(id="album-1", title="A", artist="A", created_by=OWNER))
            for number, take in enumerate(TAKES, start=1):
                session.add(Song(id=f"song-{take}", title=take, slug=f"song-{take}",
                                 album_id="album-1", track_number=number))
                session.add(Version(id=f"version-{take}", song_id=f"song-{take}",
                                    version_number=1, lyrics="", prompt=""))
            session.flush()
            session.add_all(
                Generation(id=take, song_id=f"song-{take}", version_id=f"version-{take}",
                           generation_number=1, mp3_path=f"album-1/{take}.mp3")
                for take in TAKES
            )
            for playlist, takes in (
                (TARGET, ()), ("first", FIRST_SOURCE), ("second", SECOND_SOURCE),
            ):
                session.add(Playlist(id=playlist, title=playlist, slug=playlist,
                                     created_by=OWNER))
                session.flush()
                session.add_all(
                    PlaylistEntry(playlist_id=playlist, generation_id=take, position=position)
                    for position, take in enumerate(takes)
                )

        self.client, _ = make_test_app(tmp_path, factory=pg_factory, seed_db=seed)
        seed_session(self.client, "owner")
        for take in TAKES:
            path = tmp_path / "audio" / "album-1" / f"{take}.mp3"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"mp3")

    def add_take(self, take: str) -> Callable[[], Response]:
        return lambda: self.client.post(
            f"/api/playlists/{TARGET}/entries/generation", json={"generation_id": take},
        )

    def add_playlist(self, source: str) -> Callable[[], Response]:
        return lambda: self.client.post(
            f"/api/playlists/{TARGET}/entries/playlist", json={"source_playlist_id": source},
        )

    def remove(self, entry_id: str) -> Callable[[], Response]:
        return lambda: self.client.delete(f"/api/playlists/{TARGET}/entries/{entry_id}")

    def entry_of(self, take: str) -> str:
        with self.pg_factory() as session:
            return session.query(PlaylistEntry).filter_by(
                playlist_id=TARGET, generation_id=take,
            ).one().id

    def positions(self) -> list[int]:
        with self.pg_factory() as session:
            return [
                entry.position
                for entry in session.query(PlaylistEntry).filter_by(playlist_id=TARGET)
                .order_by(PlaylistEntry.position)
            ]


def _held_at_the_playlist_lock() -> StatementPause:
    return StatementPause(after_the_playlist_lock)


def test_two_concurrent_adds_of_different_takes_store_positions_zero_and_one(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    answers = race(
        pg_factory, world.add_take("take-1"), world.add_take("take-2"),
        _held_at_the_playlist_lock(),
    )
    assert [answers["first"].status_code, answers["second"].status_code] == [200, 200]
    assert world.positions() == [0, 1]


def test_two_concurrent_playlist_adds_of_three_entries_each_store_positions_zero_to_five(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    answers = race(
        pg_factory, world.add_playlist("first"), world.add_playlist("second"),
        _held_at_the_playlist_lock(),
    )
    assert answers["first"].json()["added_count"] == 3
    assert answers["second"].json()["added_count"] == 3
    assert world.positions() == [0, 1, 2, 3, 4, 5]


def test_a_removal_and_an_add_running_together_leave_the_positions_gap_free(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    for take in ("take-1", "take-2"):
        assert world.add_take(take)().status_code == 200
    answers = race(
        pg_factory, world.remove(world.entry_of("take-1")), world.add_take("take-3"),
        _held_at_the_playlist_lock(),
    )
    assert [answers["first"].status_code, answers["second"].status_code] == [200, 200]
    assert world.positions() == [0, 1]
