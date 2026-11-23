"""Adding one playlist's playable entries to another: ownership, order, skip report, lock."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest
from httpx import Response
from support.postgres_lock_harness import (
    CommitPause,
    StatementPause,
    after_the_take_locks,
    race,
    wrote_to_tables,
)
from support.web_app import make_test_app, seed_session, seed_user

from songmaker_cli.db.models import (
    Album,
    Generation,
    Playlist,
    PlaylistEntry,
    Song,
    Version,
)
from songmaker_cli.db.queries.playlists import (
    PLAYLIST_SKIP_MISSING_AUDIO,
    PLAYLIST_SKIP_NO_PLAYABLE,
)
from songmaker_cli.db.queries.songs import soft_delete_song

OWNER = "owner-1"
OTHER = "other-1"
SOURCE = "source"
TARGET = "target"
FOREIGN = "foreign"
ADMIN_PLAYLIST = "admin-playlist"
ADMIN = "admin-1"
# The source holds its takes out of id order, one of them twice, and one in another person's album.
SOURCE_ORDER = ("take-b", "take-foreign", "take-a", "take-archived", "take-gone", "take-b")
PLAYABLE_IN_ORDER = ["take-b", "take-a", "take-b"]


def _into(playlist_id: str) -> str:
    return f"/api/playlists/{playlist_id}/entries/playlist"


class _World:
    """The real routes on PostgreSQL: a source of six entries, a target holding one, and a
    playlist of another person and of an administrator."""

    def __init__(self, pg_factory, tmp_path: Path) -> None:
        self.pg_factory = pg_factory

        def seed(session) -> None:
            seed_user(session, "owner", user_id=OWNER)
            seed_user(session, "other", user_id=OTHER)
            seed_user(session, "admin", "admin", user_id=ADMIN)
            session.flush()
            session.add(Album(id="album-1", title="A", artist="A", created_by=OWNER))
            session.add(Album(id="album-other", title="B", artist="B", created_by=OTHER))
            takes = {
                "take-a": "album-1", "take-b": "album-1", "take-archived": "album-1",
                "take-gone": "album-1", "take-foreign": "album-other",
            }
            for number, (take, album) in enumerate(takes.items(), start=1):
                session.add(Song(id=f"song-{take}", title=f"Song {take}", slug=f"song-{take}",
                                 album_id=album, track_number=number))
                session.add(Version(id=f"version-{take}", song_id=f"song-{take}",
                                    version_number=1, lyrics="", prompt=""))
            session.flush()
            session.add_all(
                Generation(
                    id=take, song_id=f"song-{take}", version_id=f"version-{take}",
                    generation_number=1, mp3_path=f"{album}/{take}.mp3",
                    is_archived=take == "take-archived",
                )
                for take, album in takes.items()
            )
            session.add_all([
                Playlist(id=SOURCE, title="Source", slug="source", created_by=OWNER),
                Playlist(id=TARGET, title="Target", slug="target", created_by=OWNER),
                Playlist(id=FOREIGN, title="Foreign", slug="foreign", created_by=OTHER),
                Playlist(id=ADMIN_PLAYLIST, title="Admin", slug="admin", created_by=ADMIN),
            ])
            session.flush()
            for playlist, takes_held in (
                (SOURCE, SOURCE_ORDER), (TARGET, ("take-a",)), (FOREIGN, ("take-foreign",)),
            ):
                session.add_all(
                    PlaylistEntry(playlist_id=playlist, generation_id=take, position=position)
                    for position, take in enumerate(takes_held)
                )

        self.client, _ = make_test_app(tmp_path, factory=pg_factory, seed_db=seed)
        seed_session(self.client, "owner")
        for take in ("take-a", "take-b", "take-archived", "take-foreign"):
            folder = "album-other" if take == "take-foreign" else "album-1"
            path = tmp_path / "audio" / folder / f"{take}.mp3"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"mp3")

    def copy(self, source: str = SOURCE, target: str = TARGET) -> Callable[[], Response]:
        return lambda: self.client.post(_into(target), json={"source_playlist_id": source})

    def bulk_delete(self, *takes: str) -> Callable[[], Response]:
        return lambda: self.client.post(
            "/api/generations/bulk-delete", json={"generation_ids": list(takes)},
        )

    def delete_song(self, song_id: str) -> None:
        with self.pg_factory() as session:
            soft_delete_song(session, song_id)
            session.commit()

    def takes_of(self, playlist_id: str) -> list[str]:
        with self.pg_factory() as session:
            return [
                entry.generation_id
                for entry in session.query(PlaylistEntry)
                .filter_by(playlist_id=playlist_id).order_by(PlaylistEntry.position)
            ]


def test_a_playlist_add_appends_the_source_playable_entries_in_order_and_reports_the_rest(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)

    response = world.copy()()

    assert response.status_code == 200
    body = response.json()
    assert body["added_count"] == len(PLAYABLE_IN_ORDER)
    assert [(item["song_id"], item["title"], item["reason"]) for item in body["skipped"]] == [
        ("song-take-archived", "Song take-archived", PLAYLIST_SKIP_NO_PLAYABLE),
        ("song-take-gone", "Song take-gone", PLAYLIST_SKIP_MISSING_AUDIO),
    ]
    assert world.takes_of(TARGET) == ["take-a", *PLAYABLE_IN_ORDER]
    assert world.takes_of(SOURCE) == list(SOURCE_ORDER)


def test_a_playlist_add_leaves_out_entries_in_an_album_the_person_cannot_open(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)

    body = world.copy()().json()

    assert "take-foreign" not in world.takes_of(TARGET)
    assert body["added_count"] == len(PLAYABLE_IN_ORDER)
    assert "song-take-foreign" not in [item["song_id"] for item in body["skipped"]]


def test_a_playlist_add_reports_an_entry_whose_song_was_deleted_as_skipped_without_its_title(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    world.delete_song("song-take-a")

    body = world.copy()().json()

    assert body["added_count"] == len(PLAYABLE_IN_ORDER) - 1
    assert ("song-take-a", "", PLAYLIST_SKIP_NO_PLAYABLE) in [
        (item["song_id"], item["title"], item["reason"]) for item in body["skipped"]
    ]
    assert world.takes_of(TARGET) == ["take-a", "take-b", "take-b"]


def test_a_playlist_add_leaves_a_deleted_song_in_an_album_the_person_cannot_open_unreported(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    world.delete_song("song-take-foreign")

    body = world.copy()().json()

    assert "song-take-foreign" not in [item["song_id"] for item in body["skipped"]]


def test_a_playlist_add_to_itself_doubles_its_playable_entries(pg_factory, tmp_path) -> None:
    world = _World(pg_factory, tmp_path)

    response = world.copy(source=SOURCE, target=SOURCE)()

    assert response.status_code == 200
    assert world.takes_of(SOURCE) == [*SOURCE_ORDER, *PLAYABLE_IN_ORDER]


@pytest.mark.parametrize(
    ("source", "target"),
    [
        pytest.param(FOREIGN, TARGET, id="source-of-another-person"),
        pytest.param(SOURCE, FOREIGN, id="target-of-another-person"),
        pytest.param("missing", TARGET, id="source-that-does-not-exist"),
        pytest.param(SOURCE, "missing", id="target-that-does-not-exist"),
    ],
)
def test_a_playlist_add_hides_playlists_the_person_does_not_own_and_writes_nothing(
    pg_factory, tmp_path, source: str, target: str,
) -> None:
    world = _World(pg_factory, tmp_path)

    response = world.copy(source=source, target=target)()

    assert response.status_code == 404
    assert response.json()["detail"] == "Playlist not found"
    assert world.takes_of(TARGET) == ["take-a"]
    assert world.takes_of(FOREIGN) == ["take-foreign"]


@pytest.mark.parametrize(
    ("source", "target"),
    [
        pytest.param(SOURCE, ADMIN_PLAYLIST, id="source-of-another-person"),
        pytest.param(ADMIN_PLAYLIST, TARGET, id="target-of-another-person"),
    ],
)
def test_a_playlist_add_does_not_let_an_administrator_copy_from_or_into_another_persons_playlist(
    pg_factory, tmp_path, source: str, target: str,
) -> None:
    world = _World(pg_factory, tmp_path)
    seed_session(world.client, "admin")

    response = world.copy(source=source, target=target)()

    assert response.status_code == 404
    assert world.takes_of(TARGET) == ["take-a"]
    assert world.takes_of(ADMIN_PLAYLIST) == []


_holding_a_generation_write = partial(
    CommitPause, lambda session: wrote_to_tables(session, "generations"),
)


def test_a_playlist_add_holding_its_take_locks_leaves_a_bulk_delete_of_them_waiting_not_deadlocked(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)

    answers = race(
        pg_factory, world.copy(), world.bulk_delete("take-a", "take-b"),
        StatementPause(after_the_take_locks),
    )

    assert answers["first"].status_code == 200
    assert answers["first"].json()["added_count"] == len(PLAYABLE_IN_ORDER)
    assert answers["second"].status_code == 200


def test_a_playlist_add_waits_for_a_delete_of_a_take_and_skips_its_song(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)

    answers = race(
        pg_factory, world.bulk_delete("take-a"), world.copy(), _holding_a_generation_write(),
    )

    assert answers["second"].status_code == 200
    body = answers["second"].json()
    assert body["added_count"] == 2
    assert world.takes_of(TARGET) == ["take-b", "take-b"]
