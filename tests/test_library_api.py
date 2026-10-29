"""Personal library — Home's Listen and Write, search, browse filters, keyset pagination."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from slugify import slugify
from sqlalchemy import event, select
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.constants import (
    LIBRARY_CURSOR_INVALID,
    LIBRARY_CURSOR_MISMATCH,
    LIBRARY_ITEM_ALBUM,
    LIBRARY_ITEM_SONG,
    LIBRARY_QUERY_REQUIRED,
    LIBRARY_SORT_NEWEST,
    LIBRARY_SORT_OLDEST,
    LIBRARY_SORT_TITLE,
    PAGE_MAX_LIMIT,
    SongWorkKind,
)
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import (
    Album,
    ChatMessage,
    Conversation,
    Generation,
    Playlist,
    PlaylistEntry,
    Song,
    User,
    UserSongWork,
    Version,
)
from songmaker_cli.library_api import LISTEN_MAX_OFFSET

USER_A = "user-a"
USER_B = "user-b"
ADMIN_ID = "user-admin"


def _ts(offset_seconds: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)


def _add_album(
    session, *, album_id: str, title: str, owner: str, created_at: datetime,
    is_archived: bool = False,
) -> Album:
    album = Album(
        id=album_id, title=title, artist="Artist",
        created_by=owner, created_at=created_at, is_archived=is_archived,
    )
    session.add(album)
    return album


def _add_song(
    session, *, song_id: str, title: str, album_id: str, created_at: datetime,
    track_number: int = 1, updated_at: datetime | None = None,
) -> Song:
    song = Song(
        id=song_id, title=title, album_id=album_id,
        track_number=track_number, created_at=created_at,
        updated_at=updated_at or created_at, slug=slugify(title),
    )
    session.add(song)
    session.add(Version(
        song_id=song_id, version_number=1, lyrics="lyrics", prompt="prompt",
    ))
    return song


def _count_queries(engine) -> tuple[list[str], Callable]:
    queries: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany) -> None:
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    return queries, _record


def _library_env(tmp_path: Path) -> tuple[object, object]:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id=USER_A, username="alice", role="user",
        ))
        session.add(User(
            id=USER_B, username="bob", role="user",
        ))
        session.add(User(
            id=ADMIN_ID, username="admin", role="admin",
        ))
        session.flush()
        _seed_library(session)
        session.commit()

    ctx = make_router_ctx(tmp_path, db=factory)
    return factory, ctx


def _client_for(ctx: object, user_id: str, role: str = "user") -> TestClient:
    app = make_router_app(
        ctx, user=make_authenticated_user(user_id, role=role, username=f"test-{user_id}")
    )
    return web_client(app)


def _make_client(
    tmp_path: Path, user_id: str, role: str = "user",
) -> tuple[TestClient, object]:
    factory, ctx = _library_env(tmp_path)
    return _client_for(ctx, user_id, role), factory


def _seed_library(session) -> None:
    _add_album(
        session, album_id="nachtstrom", title="Nachtstrom",
        owner=USER_A, created_at=_ts(100),
    )
    _add_song(
        session, song_id="song-tide", title="Tide",
        album_id="nachtstrom", created_at=_ts(110),
    )
    _add_song(
        session, song_id="song-nacht", title="Nachtstrom Remix",
        album_id="nachtstrom", created_at=_ts(120),
    )
    _add_album(
        session, album_id="alice-own", title="Alice Own",
        owner=USER_A, created_at=_ts(50),
    )
    _add_song(
        session, song_id="song-alice", title="Solo",
        album_id="alice-own", created_at=_ts(60),
    )
    _add_album(
        session, album_id="bob-secret", title="Nachtstrom",
        owner=USER_B, created_at=_ts(200),
    )
    _add_song(
        session, song_id="song-bob", title="Nachtstrom Remix",
        album_id="bob-secret", created_at=_ts(210),
    )
    _add_album(
        session, album_id="admin-own", title="Admin Own",
        owner=ADMIN_ID, created_at=_ts(10),
    )
    _add_album(
        session, album_id="percent", title="100% Live",
        owner=USER_A, created_at=_ts(5),
    )


@pytest.fixture
def library_ctx(tmp_path: Path) -> tuple[object, object]:
    return _library_env(tmp_path)


@pytest.fixture
def alice(library_ctx: tuple[object, object]) -> TestClient:
    _factory, ctx = library_ctx
    return _client_for(ctx, USER_A)


@pytest.fixture
def bob(library_ctx: tuple[object, object]) -> TestClient:
    _factory, ctx = library_ctx
    return _client_for(ctx, USER_B)


@pytest.fixture
def admin(library_ctx: tuple[object, object]) -> TestClient:
    _factory, ctx = library_ctx
    return _client_for(ctx, ADMIN_ID, role="admin")


def _collect_search(client: TestClient, q: str, sort: str, limit: int) -> list[dict]:
    items: list[dict] = []
    cursor = None
    seen_cursors: set[str] = set()
    while True:
        params: dict[str, str | int] = {"q": q, "sort": sort, "limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        resp = client.get("/api/library/search", params=params)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["has_more"] == (data["next_cursor"] is not None)
        page_ids = [(item["type"], _hit_id(item)) for item in data["items"]]
        items.extend(data["items"])
        if not data["has_more"]:
            break
        cursor = data["next_cursor"]
        assert cursor not in seen_cursors
        seen_cursors.add(cursor)
        assert page_ids, "has_more with empty page"
    return items


def _hit_id(item: dict) -> str:
    if item["type"] == LIBRARY_ITEM_ALBUM:
        return item["album"]["id"]
    return item["song"]["id"]


def _later(offset_seconds: int) -> datetime:
    """A moment after everything ``_seed_library`` dates, so a place under test leads."""
    return _ts(10_000 + offset_seconds)


def _add_take(
    session, *, generation_id: str, song_id: str, created_at: datetime,
    generation_number: int = 1, created_by: str | None = None, is_archived: bool = False,
) -> Generation:
    take = Generation(
        id=generation_id, song_id=song_id, generation_number=generation_number,
        mp3_path=f"takes/{generation_id}.mp3", created_at=created_at, created_by=created_by,
        is_archived=is_archived,
    )
    session.add(take)
    return take


def _add_cowriter_message(
    session, *, song_id: str, author: str, created_at: datetime, role: str = "user",
) -> None:
    conversation = Conversation(user_id=author)
    session.add(conversation)
    session.flush()
    session.add(ChatMessage(
        conversation_id=conversation.id, song_id=song_id, role=role,
        content="Tighten the chorus", created_at=created_at,
    ))


def _add_own_work(session, *, user_id: str, song_id: str, **work: datetime | str) -> None:
    """The person's own row on the song, holding the work columns ``work`` names."""
    session.add(UserSongWork(user_id=user_id, song_id=song_id, **work))


def _add_playlist(
    session, *, playlist_id: str, owner: str, created_at: datetime,
    last_played_at: datetime | None = None, last_played_song_id: str | None = None,
    cover_key: str | None = None,
) -> Playlist:
    playlist = Playlist(
        id=playlist_id, title=playlist_id.title(), slug=playlist_id, created_by=owner,
        created_at=created_at, updated_at=created_at,
        last_played_at=last_played_at, last_played_song_id=last_played_song_id,
        cover_key=cover_key,
    )
    session.add(playlist)
    return playlist


def _add_entry(
    session, *, playlist_id: str, generation_id: str, added_at: datetime, position: int,
) -> None:
    session.add(PlaylistEntry(
        playlist_id=playlist_id, generation_id=generation_id,
        position=position, added_at=added_at,
    ))


def _add_playable_album(session, *, album_id: str, owner: str, songs: int) -> None:
    """An album of ``songs`` songs in track order, ``<album_id>-<track>``, one take each."""
    _add_album(
        session, album_id=album_id, title=album_id.title(), owner=owner, created_at=_later(0),
    )
    for track in range(1, songs + 1):
        song_id = f"{album_id}-{track}"
        _add_song(
            session, song_id=song_id, title=f"{album_id.title()} {track}", album_id=album_id,
            created_at=_later(0), track_number=track,
        )
        _add_take(
            session, generation_id=f"{song_id}-take", song_id=song_id, created_at=_later(0),
        )
    session.flush()


def _add_playlist_of(session, *, playlist_id: str, owner: str, song_ids: list[str]) -> None:
    """A playlist holding the take of each song, in that order."""
    _add_playlist(session, playlist_id=playlist_id, owner=owner, created_at=_later(0))
    session.flush()
    for position, song_id in enumerate(song_ids):
        _add_entry(
            session, playlist_id=playlist_id, generation_id=f"{song_id}-take",
            added_at=_later(0), position=position,
        )


def _seed(factory, seed: Callable) -> None:
    with factory() as session:
        seed(session)
        session.commit()


def _listen_items(client: TestClient, **params: int) -> list[dict]:
    resp = client.get("/api/library/listen", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def _write_items(client: TestClient) -> list[dict]:
    resp = client.get("/api/library/write")
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def _both_lists(client: TestClient) -> tuple[bytes, bytes]:
    """The viewer's whole Listen and their Write, as the bytes the API answers."""
    listen = client.get("/api/library/listen", params={"limit": PAGE_MAX_LIMIT})
    write = client.get("/api/library/write")
    assert listen.status_code == write.status_code == 200
    return listen.content, write.content


def _listen_to(client: TestClient, song_id: str, playlist_id: str | None = None) -> None:
    body = None if playlist_id is None else {"playlist_id": playlist_id}
    assert client.post(f"/api/songs/{song_id}/listen", json=body).status_code == 200


def _places(items: list[dict]) -> list[tuple[str, str, str | None, int | None]]:
    return [
        (item["type"], item["id"], item["song_id"], item["song_number"]) for item in items
    ]


def _works(items: list[dict]) -> list[tuple[str, str]]:
    return [(item["song_id"], item["work"]) for item in items]


def test_creating_renaming_and_editing_move_write_and_leave_listen_byte_identical(
    library_ctx: tuple[object, object],
) -> None:
    factory, ctx = library_ctx

    def seed(session) -> None:
        _add_playable_album(session, album_id="quiet", owner=USER_A, songs=3)
        _add_playlist_of(session, playlist_id="late-drive", owner=USER_A, song_ids=["quiet-2"])

    _seed(factory, seed)
    alice = _client_for(ctx, USER_A)
    _listen_to(alice, "quiet-1")
    _listen_to(alice, "quiet-2", playlist_id="late-drive")
    listen_before = alice.get("/api/library/listen").content

    created = alice.post("/api/albums", json={"title": "Fresh", "artist": "Alice"})
    assert created.status_code == 200, created.text
    song = alice.post("/api/songs", json={"title": "New Song", "album_id": created.json()["id"]})
    assert song.status_code == 200, song.text
    assert alice.put("/api/albums/quiet", json={"subtitle": "Live"}).status_code == 200
    assert alice.put("/api/songs/quiet-3/title", json={"title": "Renamed"}).status_code == 200
    assert alice.put("/api/songs/quiet-1", json={"lyrics": "new words"}).status_code == 200

    assert alice.get("/api/library/listen").content == listen_before
    assert _works(_write_items(alice)) == [
        ("quiet-1", SongWorkKind.LYRICS),
        ("quiet-3", SongWorkKind.RENAMED),
        (song.json()["id"], SongWorkKind.CREATED),
    ]


@pytest.mark.parametrize(
    ("deleted_songs", "song_number"),
    [((), 5), (("quiet-2",), 4)],
    ids=["song-five", "song-five-after-song-two-left"],
)
def test_a_listen_puts_its_album_first_naming_the_song_by_its_place(
    library_ctx: tuple[object, object], deleted_songs: tuple[str, ...], song_number: int,
) -> None:
    factory, ctx = library_ctx
    _seed(factory, lambda session: _add_playable_album(
        session, album_id="quiet", owner=USER_A, songs=7,
    ))
    alice = _client_for(ctx, USER_A)
    _listen_to(alice, "quiet-1")
    with factory() as session:
        _add_playable_album(session, album_id="later", owner=USER_A, songs=1)
        for song_id in deleted_songs:
            session.get(Song, song_id).deleted_at = _later(1)
        session.commit()
    _listen_to(alice, "later-1")

    _listen_to(alice, "quiet-5")

    items = _listen_items(alice)
    assert _places(items) == [
        ("album", "quiet", "quiet-5", song_number),
        ("album", "later", "later-1", 1),
    ]
    assert items[0]["song_title"] == "Quiet 5"


def test_a_listen_inside_a_playlist_lifts_the_playlist_and_leaves_the_album(
    library_ctx: tuple[object, object],
) -> None:
    factory, ctx = library_ctx

    def seed(session) -> None:
        _add_playable_album(session, album_id="quiet", owner=USER_A, songs=3)
        _add_playlist_of(
            session, playlist_id="late-drive", owner=USER_A,
            song_ids=["quiet-3", "quiet-1", "quiet-2"],
        )

    _seed(factory, seed)
    alice = _client_for(ctx, USER_A)
    _listen_to(alice, "quiet-3", playlist_id="late-drive")
    assert _places(_listen_items(alice)) == [("playlist", "late-drive", "quiet-3", 1)]

    _listen_to(alice, "quiet-1")
    album_before = next(item for item in _listen_items(alice) if item["type"] == "album")

    _listen_to(alice, "quiet-2", playlist_id="late-drive")

    items = _listen_items(alice)
    assert _places(items) == [
        ("playlist", "late-drive", "quiet-2", 3),
        ("album", "quiet", "quiet-1", 1),
    ]
    assert items[1] == album_before


def test_1354_47_A5_an_admins_actions_leave_the_owners_lists_byte_identical_and_move_the_admins_own(
    library_ctx: tuple[object, object],
) -> None:
    """1354_rule_6: each viewer's lists reflect only their own activity."""
    factory, ctx = library_ctx

    def seed(session) -> None:
        _add_playable_album(session, album_id="vernissage", owner=USER_B, songs=2)
        _add_playlist_of(
            session, playlist_id="admin-mix", owner=ADMIN_ID, song_ids=["vernissage-2"],
        )

    _seed(factory, seed)
    bob = _client_for(ctx, USER_B)
    admin = _client_for(ctx, ADMIN_ID, role="admin")
    _listen_to(bob, "vernissage-1")
    assert bob.put("/api/songs/vernissage-1", json={"lyrics": "leonardo"}).status_code == 200
    owners_lists = _both_lists(bob)
    assert _listen_items(admin) == _write_items(admin) == []

    _listen_to(admin, "vernissage-2")
    _listen_to(admin, "vernissage-2", playlist_id="admin-mix")
    assert admin.put("/api/songs/vernissage-2", json={"prompt": "felix"}).status_code == 200
    assert admin.put("/api/songs/vernissage-2/title", json={"title": "Felix"}).status_code == 200
    with factory() as session:
        _add_take(
            session, generation_id="admin-take", song_id="vernissage-1",
            created_at=_later(10), generation_number=2, created_by=ADMIN_ID,
        )
        _add_cowriter_message(
            session, song_id="vernissage-1", author=ADMIN_ID, created_at=_later(20),
        )
        session.commit()
        admin_entry_id = session.scalars(
            select(PlaylistEntry.id).where(PlaylistEntry.playlist_id == "admin-mix"),
        ).one()

    assert _both_lists(bob) == owners_lists
    assert all(item["entry_id"] is None for item in _listen_items(bob))
    assert next(
        item for item in _listen_items(admin) if item["type"] == "playlist"
    )["entry_id"] == admin_entry_id
    assert _places(_listen_items(admin)) == [
        ("playlist", "admin-mix", "vernissage-2", 1),
        ("album", "vernissage", "vernissage-2", 2),
    ]
    assert _works(_write_items(admin)) == [
        ("vernissage-2", SongWorkKind.RENAMED),
        ("vernissage-1", SongWorkKind.COWRITER),
    ]


def test_a_musicians_lists_ignore_their_own_records_on_albums_they_cannot_open(
    library_ctx: tuple[object, object],
) -> None:
    factory, ctx = library_ctx
    alice = _client_for(ctx, USER_A)
    before = _both_lists(alice)

    with factory() as session:
        _add_own_work(
            session, user_id=USER_A, song_id="song-bob", edited_at=_later(10),
            edit_kind=SongWorkKind.LYRICS, album_played_at=_later(10),
        )
        _add_take(
            session, generation_id="take-alice", song_id="song-bob", created_at=_later(20),
            created_by=USER_A,
        )
        _add_cowriter_message(session, song_id="song-bob", author=USER_A, created_at=_later(30))
        session.commit()

    assert _both_lists(alice) == before


def _seed_legacy_listen_only(session) -> None:
    _add_own_work(
        session, user_id=USER_A, song_id="song-tide",
        played_at=_later(10),
    )


def _seed_listen_on_a_deleted_song(session) -> None:
    _add_own_work(
        session, user_id=USER_A, song_id="song-tide", album_played_at=_later(10),
    )
    session.flush()
    session.get(Song, "song-tide").deleted_at = _later(11)


def _seed_listen_in_an_archived_album(session) -> None:
    _add_own_work(
        session, user_id=USER_A, song_id="song-tide", album_played_at=_later(10),
    )
    session.get(Album, "nachtstrom").is_archived = True


def _seed_listen_in_a_deleted_album(session) -> None:
    _add_own_work(
        session, user_id=USER_A, song_id="song-tide", album_played_at=_later(10),
    )
    session.get(Album, "nachtstrom").deleted_at = _later(11)


@pytest.mark.parametrize(
    "seed",
    [
        _seed_legacy_listen_only,
        _seed_listen_on_a_deleted_song,
        _seed_listen_in_an_archived_album,
        _seed_listen_in_a_deleted_album,
    ],
    ids=[
        "legacy-listen-without-an-album-listen",
        "deleted-song",
        "archived-album",
        "deleted-album",
    ],
)
def test_listen_leaves_out_an_album_without_a_live_album_listen(
    tmp_path: Path, seed: Callable,
) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    _seed(factory, seed)

    assert _listen_items(client) == []


def test_1354_47_A5_an_album_falls_back_to_its_newest_listened_live_song(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)

    def seed(session) -> None:
        for song_id, offset in (("song-tide", 10), ("song-nacht", 20)):
            _add_own_work(
                session, user_id=USER_A, song_id=song_id,
                album_played_at=_later(offset),
            )
        session.flush()
        session.get(Song, "song-nacht").deleted_at = _later(21)

    _seed(factory, seed)

    items = _listen_items(client)
    assert _places(items) == [("album", "nachtstrom", "song-tide", 1)]
    assert items[0]["played_at"] == _later(10).isoformat()
    assert items[0]["entry_id"] is None


def _seed_played_playlist(session, *, entries: list[str], last_played_song_id: str) -> None:
    """Alice's ``late-drive`` played last at ``last_played_song_id``.

    It may hold album ``quiet``'s three songs and ``aside-1``, the one song of
    album ``aside``, which a removal below can take out of the playlist's live
    entries.
    """
    _add_playable_album(session, album_id="quiet", owner=USER_A, songs=3)
    _add_playable_album(session, album_id="aside", owner=USER_A, songs=1)
    _add_playlist_of(session, playlist_id="late-drive", owner=USER_A, song_ids=entries)
    playlist = session.get(Playlist, "late-drive")
    for index, entry in enumerate(sorted(playlist.entries, key=lambda entry: entry.position)):
        entry.id = f"entry-{len(entries) - index}"
    playlist.last_played_at = _later(40)
    playlist.last_played_song_id = last_played_song_id


_AN_ENTRY_STOPS_BEING_LIVE = pytest.mark.parametrize(
    "remove_aside",
    [
        lambda session: setattr(session.get(Song, "aside-1"), "deleted_at", _later(41)),
        lambda session: setattr(session.get(Generation, "aside-1-take"), "is_archived", True),
        lambda session: setattr(session.get(Album, "aside"), "is_archived", True),
        lambda session: setattr(session.get(Album, "aside"), "deleted_at", _later(41)),
        lambda session: setattr(session.get(Album, "aside"), "created_by", USER_B),
    ],
    ids=[
        "deleted-song",
        "archived-take",
        "archived-album",
        "deleted-album",
        "album-the-viewer-may-not-open",
    ],
)


def _played_playlist_item(
    tmp_path: Path, *, entries: list[str], last_played_song_id: str,
    remove: Callable | None = None,
) -> dict:
    """The one item Alice's Listen shows for her played ``late-drive``."""
    client, factory = _make_client(tmp_path, USER_A)

    def seed(session) -> None:
        _seed_played_playlist(session, entries=entries, last_played_song_id=last_played_song_id)

    _seed(factory, seed)
    _listen_to(client, last_played_song_id, playlist_id="late-drive")
    with factory() as session:
        played_at = session.get(Playlist, "late-drive").last_played_at
    if remove is not None:
        _seed(factory, remove)

    [item] = _listen_items(client)
    assert item["played_at"] == played_at.replace(tzinfo=timezone.utc).isoformat()
    return item


_RESUMES_FROM_THE_START = {
    "type": "playlist", "id": "late-drive", "song_id": None, "song_title": None,
    "song_number": None, "entry_id": None,
}


@pytest.mark.parametrize(
    ("entries", "song_number", "entry_id", "change"),
    [
        (["quiet-1", "quiet-2", "quiet-3"], 3, "entry-1", None),
        (["quiet-1", "quiet-3", "quiet-3"], 2, "entry-2", None),
        (["quiet-1", "quiet-3", "quiet-3"], 2, "entry-1",
         lambda session: setattr(session.get(PlaylistEntry, "entry-1"), "position", 1)),
        (["quiet-1", "quiet-3"], 2, "entry-1",
         lambda session: setattr(session.get(Generation, "quiet-3-take"), "mp3_path", "")),
    ],
    ids=["1354_47_A1", "1354_47_A2", "1354_47_A2-equal-position", "1354_47_A6"],
)
def test_1354_47_a_played_playlist_names_its_first_live_entry(
    tmp_path: Path, entries: list[str], song_number: int, entry_id: str,
    change: Callable | None,
) -> None:
    item = _played_playlist_item(
        tmp_path, entries=entries, last_played_song_id="quiet-3", remove=change,
    )

    assert _places([item]) == [("playlist", "late-drive", "quiet-3", song_number)]
    assert item["song_title"] == "Quiet 3"
    assert item["entry_id"] == entry_id


@_AN_ENTRY_STOPS_BEING_LIVE
def test_1354_47_A3_an_entry_that_is_no_longer_live_never_raises_a_later_songs_number(
    tmp_path: Path, remove_aside: Callable,
) -> None:
    """1354_rule_20: filtered entries do not contribute to live numbering."""
    item = _played_playlist_item(
        tmp_path, entries=["aside-1", "quiet-1", "quiet-2"], last_played_song_id="quiet-2",
        remove=remove_aside,
    )

    assert _places([item]) == [("playlist", "late-drive", "quiet-2", 2)]
    assert item["entry_id"] == "entry-1"


@_AN_ENTRY_STOPS_BEING_LIVE
def test_1354_47_A4_a_playlist_without_a_live_occurrence_resumes_from_the_start(
    tmp_path: Path, remove_aside: Callable,
) -> None:
    """1354_rule_20: filtered targets expose no entry identity."""
    item = _played_playlist_item(
        tmp_path, entries=["quiet-1", "aside-1"], last_played_song_id="aside-1",
        remove=remove_aside,
    )

    assert {key: item[key] for key in _RESUMES_FROM_THE_START} == _RESUMES_FROM_THE_START


def test_1354_47_A4_a_playlist_whose_last_played_song_left_it_resumes_from_the_start(
    tmp_path: Path,
) -> None:
    """1354_rule_20: removed targets expose no entry identity."""
    item = _played_playlist_item(
        tmp_path, entries=["quiet-1", "aside-1"], last_played_song_id="aside-1",
        remove=lambda session: session.delete(session.get(PlaylistEntry, "entry-1")),
    )

    assert {key: item[key] for key in _RESUMES_FROM_THE_START} == _RESUMES_FROM_THE_START


def test_listen_leaves_out_a_playlist_never_played_and_one_deleted(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)

    def seed(session) -> None:
        _seed_played_playlist(session, entries=["quiet-1"], last_played_song_id="quiet-1")
        _add_playlist_of(session, playlist_id="never-played", owner=USER_A, song_ids=["quiet-2"])

    _seed(factory, seed)
    assert [item["id"] for item in _listen_items(client)] == ["late-drive"]

    assert client.delete("/api/playlists/late-drive").status_code in (200, 204)

    assert _listen_items(client) == []


def test_listen_shows_three_places_newest_first_ties_album_before_playlist_then_id(
    tmp_path: Path,
) -> None:
    client, factory = _make_client(tmp_path, USER_A)

    def seed(session) -> None:
        for song_id, offset in (("song-tide", 50), ("song-alice", 50)):
            _add_own_work(
                session, user_id=USER_A, song_id=song_id,
                album_played_at=_later(offset),
            )
        for playlist_id, offset in (("playlist-b", 50), ("playlist-a", 50), ("playlist-c", 40)):
            _add_playlist(
                session, playlist_id=playlist_id, owner=USER_A, created_at=_later(0),
                last_played_at=_later(offset),
            )

    _seed(factory, seed)

    assert [(item["type"], item["id"]) for item in _listen_items(client)] == [
        ("album", "alice-own"),
        ("album", "nachtstrom"),
        ("playlist", "playlist-a"),
    ]


def test_listen_tiles_carry_the_cover_the_place_page_shows(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)

    def seed(session) -> None:
        _add_playable_album(session, album_id="covered", owner=USER_A, songs=1)
        session.get(Album, "covered").cover_key = "album-key"
        _add_own_work(
            session, user_id=USER_A, song_id="covered-1",
            album_played_at=_later(20),
        )
        _add_playlist_of(session, playlist_id="mosaic", owner=USER_A, song_ids=["covered-1"])
        session.get(Playlist, "mosaic").last_played_at = _later(30)
        _add_playlist(
            session, playlist_id="uploaded", owner=USER_A, created_at=_later(0),
            last_played_at=_later(10), cover_key="playlist-key",
        )

    _seed(factory, seed)

    items = {item["id"]: item for item in _listen_items(client)}
    assert items["covered"]["cover"]["card"] == (
        "/api/albums/covered/cover?variant=card&v=album-key"
    )
    assert items["covered"]["album_covers"] == []
    assert items["mosaic"]["cover"] is None
    assert items["mosaic"]["album_covers"] == [items["covered"]["cover"]]
    assert items["uploaded"]["cover"]["card"] == (
        "/api/playlists/uploaded/cover?variant=card&v=playlist-key"
    )


def _add_album_the_viewer_listened_in(session, *, viewer_id: str, index: int) -> None:
    owner = viewer_id if index % 2 == 0 else USER_B
    _add_playable_album(session, album_id=f"album-{index}", owner=owner, songs=1)
    _add_own_work(
        session, user_id=viewer_id, song_id=f"album-{index}-1",
        album_played_at=_later(index),
    )


def _add_playlist_the_viewer_listened_in(session, *, viewer_id: str, index: int) -> None:
    _add_playlist(
        session, playlist_id=f"playlist-{index}", owner=viewer_id, created_at=_later(0),
        last_played_at=_later(index),
    )


@pytest.mark.parametrize(
    ("window", "expected_indexes"),
    [
        ({}, [7, 6, 5]),
        ({"limit": 8}, [7, 6, 5, 4, 3, 2, 1, 0]),
        ({"offset": 5, "limit": 3}, [2, 1, 0]),
        ({"offset": 7, "limit": PAGE_MAX_LIMIT}, [0]),
        ({"offset": 8, "limit": 3}, []),
    ],
    ids=["default-three", "all", "middle-window", "last-page", "past-the-end"],
)
def test_an_admins_listen_returns_the_window_of_places_asked_for(
    tmp_path: Path, window: dict[str, int], expected_indexes: list[int],
) -> None:
    client, factory = _make_client(tmp_path, ADMIN_ID, role="admin")

    def seed(session) -> None:
        for index in range(8):
            add_place = (
                _add_album_the_viewer_listened_in if index % 3
                else _add_playlist_the_viewer_listened_in
            )
            add_place(session, viewer_id=ADMIN_ID, index=index)

    _seed(factory, seed)

    items = _listen_items(client, **window)

    assert [item["id"].rsplit("-", 1)[1] for item in items] == [
        str(index) for index in expected_indexes
    ]


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/api/library/continue", 404),
        ("/api/library/listen", 401),
        ("/api/library/write", 401),
    ],
    ids=["continue-is-gone", "listen-needs-a-session", "write-needs-a-session"],
)
def test_home_lists_answer_only_a_signed_in_musician_and_continue_is_gone(
    library_ctx: tuple[object, object], path: str, status: int,
) -> None:
    _factory, ctx = library_ctx
    signed_out = web_client(make_router_app(ctx))

    assert signed_out.get(path).status_code == status


@pytest.mark.parametrize(
    "window",
    [
        {"limit": 0},
        {"limit": PAGE_MAX_LIMIT + 1},
        {"offset": -1},
        {"offset": LISTEN_MAX_OFFSET + 1},
    ],
)
def test_listen_refuses_a_window_outside_its_bound(
    alice: TestClient, window: dict[str, int],
) -> None:
    assert alice.get("/api/library/listen", params=window).status_code == 422


def _seed_song_created(session) -> None:
    _add_own_work(
        session, user_id=USER_A, song_id="song-tide", edited_at=_later(10),
        edit_kind=SongWorkKind.CREATED,
    )


def _seed_legacy_edit_without_a_kind(session) -> None:
    _add_own_work(session, user_id=USER_A, song_id="song-tide", edited_at=_later(10))


def _seed_own_take(session) -> None:
    _add_take(
        session, generation_id="own-take", song_id="song-tide", created_at=_later(10),
        created_by=USER_A,
    )


def _seed_own_cowriter_message(session) -> None:
    _add_cowriter_message(session, song_id="song-tide", author=USER_A, created_at=_later(10))


@pytest.mark.parametrize(
    ("seed", "work"),
    [
        (_seed_song_created, SongWorkKind.CREATED),
        (_seed_legacy_edit_without_a_kind, SongWorkKind.EDITED),
        (_seed_own_take, SongWorkKind.TAKE),
        (_seed_own_cowriter_message, SongWorkKind.COWRITER),
    ],
    ids=["created", "legacy-edit-reads-as-edited", "take", "co-writer-message"],
)
def test_write_names_each_kind_of_own_work_once(
    tmp_path: Path, seed: Callable, work: SongWorkKind,
) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    _seed(factory, seed)

    assert _write_items(client) == [{
        "song_id": "song-tide",
        "song_title": "Tide",
        "album_id": "nachtstrom",
        "album_title": "Nachtstrom",
        "cover": None,
        "album_cover": None,
        "work": work,
        "worked_at": _later(10).isoformat(),
    }]


@pytest.mark.parametrize(
    ("request_body", "work"),
    [
        ({"lyrics": "new words"}, SongWorkKind.LYRICS),
        ({"prompt": "dark synthwave", "bpm": 90}, SongWorkKind.STYLE),
    ],
    ids=["lyrics", "style"],
)
def test_a_saved_edit_leads_write_with_its_kind(
    alice: TestClient, request_body: dict, work: SongWorkKind,
) -> None:
    assert alice.put("/api/songs/song-tide", json=request_body).status_code == 200

    assert _works(_write_items(alice)) == [("song-tide", work)]


def test_the_newest_kind_of_work_on_a_song_wins_and_listens_never_count(
    library_ctx: tuple[object, object],
) -> None:
    factory, ctx = library_ctx
    alice = _client_for(ctx, USER_A)
    with factory() as session:
        _add_take(
            session, generation_id="tide-take", song_id="song-tide", created_at=_ts(0),
            created_by=USER_A,
        )
        _add_take(session, generation_id="nacht-take", song_id="song-nacht", created_at=_ts(0))
        session.commit()
    assert alice.put("/api/songs/song-tide", json={"lyrics": "new words"}).status_code == 200
    assert alice.put("/api/songs/song-alice/title", json={"title": "Duet"}).status_code == 200
    write_before = _write_items(alice)

    _listen_to(alice, "song-tide")
    _listen_to(alice, "song-nacht")

    assert _works(_write_items(alice)) == _works(write_before) == [
        ("song-alice", SongWorkKind.RENAMED),
        ("song-tide", SongWorkKind.LYRICS),
    ]


@pytest.mark.parametrize(
    "seed",
    [
        partial(_add_take, generation_id="archived", is_archived=True, created_by=USER_A),
        partial(_add_take, generation_id="unattributed"),
        partial(_add_take, generation_id="bobs", created_by=USER_B),
        partial(_add_cowriter_message, author=USER_A, role="assistant"),
        partial(_add_cowriter_message, author=USER_B),
    ],
    ids=[
        "archived-take",
        "take-without-a-recorded-maker",
        "another-musicians-take",
        "co-writer-reply",
        "another-musicians-message",
    ],
)
def test_write_leaves_out_work_that_is_not_the_viewers_own_or_is_archived(
    tmp_path: Path, seed: Callable,
) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    _seed(factory, lambda session: seed(session, song_id="song-tide", created_at=_later(10)))

    assert _write_items(client) == []


def test_unarchiving_a_take_restores_it_to_write(alice: TestClient, library_ctx) -> None:
    factory, _ctx = library_ctx
    _seed(factory, lambda session: _add_take(
        session, generation_id="archived", song_id="song-tide", created_at=_later(10),
        created_by=USER_A, is_archived=True,
    ))
    assert _write_items(alice) == []

    with factory() as session:
        session.get(Generation, "archived").is_archived = False
        session.commit()

    assert _works(_write_items(alice)) == [("song-tide", SongWorkKind.TAKE)]


@pytest.mark.parametrize(
    "remove",
    [
        lambda session: setattr(session.get(Song, "song-tide"), "deleted_at", _later(11)),
        lambda session: setattr(session.get(Album, "nachtstrom"), "is_archived", True),
        lambda session: setattr(session.get(Album, "nachtstrom"), "deleted_at", _later(11)),
    ],
    ids=["deleted-song", "archived-album", "deleted-album"],
)
def test_write_leaves_out_a_song_that_was_removed(tmp_path: Path, remove: Callable) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    _seed(factory, _seed_own_take)
    assert _works(_write_items(client)) == [("song-tide", SongWorkKind.TAKE)]

    _seed(factory, remove)

    assert _write_items(client) == []


def test_write_shows_the_three_songs_worked_on_last_with_their_covers(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)

    def seed(session) -> None:
        session.get(Album, "nachtstrom").cover_key = "album-key"
        session.get(Song, "song-tide").cover_key = "song-key"
        for song_id, offset in (
            ("song-tide", 30), ("song-nacht", 30), ("song-alice", 20), ("song-bob", 40),
        ):
            _add_own_work(session, user_id=USER_A, song_id=song_id, edited_at=_later(offset))
        _add_playable_album(session, album_id="older", owner=USER_A, songs=1)
        _add_own_work(session, user_id=USER_A, song_id="older-1", edited_at=_later(10))

    _seed(factory, seed)

    items = _write_items(client)
    assert [item["song_id"] for item in items] == ["song-nacht", "song-tide", "song-alice"]
    assert items[1]["cover"]["card"] == "/api/songs/song-tide/cover?variant=card&v=song-key"
    assert items[1]["album_cover"]["card"] == (
        "/api/albums/nachtstrom/cover?variant=card&v=album-key"
    )
    assert items[0]["cover"] is None


def _seed_busy_library(session, *, viewer_id: str) -> None:
    for index in range(8):
        album_id = f"busy-{index}"
        _add_playable_album(session, album_id=album_id, owner=USER_A, songs=1)
        song_id = f"{album_id}-1"
        _add_own_work(
            session, user_id=viewer_id, song_id=song_id, edited_at=_later(index),
            edit_kind=SongWorkKind.LYRICS, album_played_at=_later(index),
        )
        _add_take(
            session, generation_id=f"{album_id}-own-take", song_id=song_id,
            created_at=_later(index), generation_number=2, created_by=viewer_id,
        )
        _add_cowriter_message(
            session, song_id=song_id, author=viewer_id, created_at=_later(index),
        )
        _add_playlist_of(
            session, playlist_id=f"list-{index}", owner=viewer_id, song_ids=[song_id],
        )
        session.get(Playlist, f"list-{index}").last_played_at = _later(index)
        session.get(Playlist, f"list-{index}").last_played_song_id = song_id


@pytest.mark.parametrize(
    ("viewer_id", "role"),
    [(USER_A, "user"), (ADMIN_ID, "admin")],
    ids=["musician", "admin-reading-foreign-albums-too"],
)
@pytest.mark.parametrize(
    ("path", "items", "statements"),
    [("/api/library/listen?limit=8", 8, 3), ("/api/library/write", 3, 1)],
    ids=["listen", "write"],
)
def test_home_lists_read_in_a_fixed_number_of_statements(
    tmp_path: Path, viewer_id: str, role: str, path: str, items: int, statements: int,
) -> None:
    client, factory = _make_client(tmp_path, viewer_id, role)
    with factory() as session:
        _seed_busy_library(session, viewer_id=viewer_id)
        session.commit()
        engine = session.get_bind()

    queries, handle = _count_queries(engine)
    try:
        resp = client.get(path)
    finally:
        event.remove(engine, "before_cursor_execute", handle)

    assert resp.status_code == 200
    assert len(resp.json()["items"]) == items
    assert len(queries) == statements, f"expected {statements} statements, got {queries}"


def test_search_requires_query(alice: TestClient) -> None:
    assert alice.get("/api/library/search").status_code == 422
    assert alice.get("/api/library/search", params={"q": ""}).status_code == 422
    resp = alice.get("/api/library/search", params={"q": "   "})
    assert resp.status_code == 422
    assert resp.json()["detail"] == LIBRARY_QUERY_REQUIRED


def test_search_album_title_nachtstrom(alice: TestClient) -> None:
    resp = alice.get("/api/library/search", params={"q": "nachtstrom"})
    assert resp.status_code == 200
    data = resp.json()
    types_and_ids = [(item["type"], _hit_id(item)) for item in data["items"]]
    assert (LIBRARY_ITEM_ALBUM, "nachtstrom") in types_and_ids
    album_hit = next(
        item for item in data["items"]
        if item["type"] == LIBRARY_ITEM_ALBUM and item["album"]["id"] == "nachtstrom"
    )
    assert album_hit["album"]["title"] == "Nachtstrom"


def test_search_album_hit_says_whether_it_has_a_playable_take_1354_rule_11(
    library_ctx: tuple[object, object],
) -> None:
    factory, ctx = library_ctx

    def _seed_takes(session) -> None:
        _add_take(
            session, generation_id="tide-take", song_id="song-tide", created_at=_later(0),
        )
        _add_take(
            session, generation_id="solo-take", song_id="song-alice", created_at=_later(0),
            is_archived=True,
        )

    _seed(factory, _seed_takes)
    alice = _client_for(ctx, USER_A)
    items = alice.get("/api/library/search", params={"q": "o"}).json()["items"]
    reported = {
        item["album"]["id"]: item["album"]["has_playable_take"]
        for item in items if item["type"] == LIBRARY_ITEM_ALBUM
    }
    assert reported["nachtstrom"] is True
    assert reported["alice-own"] is False


def test_search_song_title_includes_album_context(alice: TestClient) -> None:
    resp = alice.get("/api/library/search", params={"q": "remix"})
    assert resp.status_code == 200
    songs = [item for item in resp.json()["items"] if item["type"] == LIBRARY_ITEM_SONG]
    assert len(songs) == 1
    hit = songs[0]
    assert hit["song"]["id"] == "song-nacht"
    assert hit["album_id"] == "nachtstrom"
    assert hit["album_title"] == "Nachtstrom"
    assert hit["song"]["album_id"] == "nachtstrom"
    assert hit["song"]["album_title"] == "Nachtstrom"


def test_search_is_case_insensitive(alice: TestClient) -> None:
    upper = alice.get("/api/library/search", params={"q": "NACHTSTROM"}).json()
    lower = alice.get("/api/library/search", params={"q": "nachtstrom"}).json()
    assert [_hit_id(i) for i in upper["items"]] == [_hit_id(i) for i in lower["items"]]


def test_user_b_never_sees_user_a_titles(alice: TestClient, bob: TestClient) -> None:
    alice_hits = {
        (item["type"], _hit_id(item))
        for item in alice.get("/api/library/search", params={"q": "nachtstrom"}).json()["items"]
    }
    bob_hits = {
        (item["type"], _hit_id(item))
        for item in bob.get("/api/library/search", params={"q": "nachtstrom"}).json()["items"]
    }
    assert (LIBRARY_ITEM_ALBUM, "nachtstrom") in alice_hits
    assert (LIBRARY_ITEM_SONG, "song-nacht") in alice_hits
    assert (LIBRARY_ITEM_ALBUM, "bob-secret") not in alice_hits
    assert (LIBRARY_ITEM_SONG, "song-bob") not in alice_hits
    assert (LIBRARY_ITEM_ALBUM, "bob-secret") in bob_hits
    assert (LIBRARY_ITEM_SONG, "song-bob") in bob_hits
    assert (LIBRARY_ITEM_ALBUM, "nachtstrom") not in bob_hits
    assert (LIBRARY_ITEM_SONG, "song-nacht") not in bob_hits

    alice_albums = {a["id"] for a in alice.get("/api/albums").json()["items"]}
    bob_albums = {a["id"] for a in bob.get("/api/albums").json()["items"]}
    assert "nachtstrom" in alice_albums
    assert "bob-secret" not in alice_albums
    assert "bob-secret" in bob_albums
    assert "nachtstrom" not in bob_albums

    alice_songs = {s["id"] for s in alice.get("/api/songs").json()["items"]}
    bob_songs = {s["id"] for s in bob.get("/api/songs").json()["items"]}
    assert "song-nacht" in alice_songs
    assert "song-bob" not in alice_songs
    assert "song-bob" in bob_songs
    assert "song-nacht" not in bob_songs


def test_admin_search_finds_every_album_and_song_the_admin_can_open(admin: TestClient) -> None:
    albums = {a["id"] for a in admin.get("/api/albums").json()["items"]}
    hits = {
        (item["type"], _hit_id(item))
        for item in admin.get("/api/library/search", params={"q": "nachtstrom"}).json()["items"]
    }
    assert {"nachtstrom", "bob-secret"} <= albums
    assert hits == {
        (LIBRARY_ITEM_ALBUM, "nachtstrom"),
        (LIBRARY_ITEM_SONG, "song-nacht"),
        (LIBRARY_ITEM_ALBUM, "bob-secret"),
        (LIBRARY_ITEM_SONG, "song-bob"),
    }


def test_search_keyset_pages_without_dupes_or_gaps(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        for i in range(8):
            _add_album(
                session,
                album_id=f"page-a{i:02d}",
                title=f"Catalog {i:02d}",
                owner=USER_A,
                created_at=_ts(1000 + i),
            )
            _add_song(
                session,
                song_id=f"page-s{i:02d}",
                title=f"Catalog Song {i:02d}",
                album_id=f"page-a{i:02d}",
                created_at=_ts(2000 + i),
            )
        session.commit()

    items = _collect_search(client, q="Catalog", sort=LIBRARY_SORT_NEWEST, limit=3)
    keys = [(item["type"], _hit_id(item)) for item in items]
    assert len(keys) == 16
    assert len(set(keys)) == 16
    expected_songs = [(LIBRARY_ITEM_SONG, f"page-s{i:02d}") for i in range(7, -1, -1)]
    expected_albums = [(LIBRARY_ITEM_ALBUM, f"page-a{i:02d}") for i in range(7, -1, -1)]
    assert keys == expected_songs + expected_albums


def test_search_title_sort_album_before_song_then_id(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="z-album", title="Same Title",
            owner=USER_A, created_at=_ts(1),
        )
        _add_song(
            session, song_id="a-song", title="Same Title",
            album_id="z-album", created_at=_ts(1),
        )
        session.commit()
    resp = client.get(
        "/api/library/search",
        params={"q": "Same Title", "sort": LIBRARY_SORT_TITLE},
    )
    keys = [(i["type"], _hit_id(i)) for i in resp.json()["items"]]
    assert keys[0] == (LIBRARY_ITEM_ALBUM, "z-album")
    assert keys[1] == (LIBRARY_ITEM_SONG, "a-song")


def test_insert_after_first_page_does_not_appear_on_second(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        for i in range(4):
            _add_album(
                session,
                album_id=f"ks-a{i}",
                title=f"Keyset {i}",
                owner=USER_A,
                created_at=_ts(3000 + i),
            )
        session.commit()

    first = client.get(
        "/api/library/search",
        params={"q": "Keyset", "sort": LIBRARY_SORT_NEWEST, "limit": 2},
    ).json()
    assert first["has_more"] is True
    cursor = first["next_cursor"]
    first_ids = [_hit_id(i) for i in first["items"]]
    assert first_ids == ["ks-a3", "ks-a2"]

    with factory() as session:
        _add_album(
            session, album_id="ks-new", title="Keyset newest",
            owner=USER_A, created_at=_ts(4000),
        )
        session.commit()

    second = client.get(
        "/api/library/search",
        params={"q": "Keyset", "sort": LIBRARY_SORT_NEWEST, "limit": 2, "cursor": cursor},
    ).json()
    second_ids = [_hit_id(i) for i in second["items"]]
    assert "ks-new" not in second_ids
    assert "ks-a3" not in second_ids
    assert "ks-a2" not in second_ids
    assert second_ids == ["ks-a1", "ks-a0"]


def test_cursor_mismatch_and_tampering_are_rejected(alice: TestClient) -> None:
    """1301-F13-HTTP: invalid signatures return the existing 422 error body."""
    first = alice.get(
        "/api/library/search",
        params={"q": "nachtstrom", "sort": LIBRARY_SORT_NEWEST, "limit": 1},
    ).json()
    cursor = first["next_cursor"]
    assert cursor

    mismatch = alice.get(
        "/api/library/search",
        params={"q": "tide", "sort": LIBRARY_SORT_NEWEST, "cursor": cursor},
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"] == LIBRARY_CURSOR_MISMATCH

    sort_mismatch = alice.get(
        "/api/library/search",
        params={"q": "nachtstrom", "sort": LIBRARY_SORT_TITLE, "cursor": cursor},
    )
    assert sort_mismatch.status_code == 422
    assert sort_mismatch.json()["detail"] == LIBRARY_CURSOR_MISMATCH

    for invalid_cursor in (
        cursor[:-1] + ("0" if cursor[-1] != "0" else "1"),
        cursor + "é",
        "not-a-cursor",
    ):
        response = alice.get(
            "/api/library/search",
            params={"q": "nachtstrom", "cursor": invalid_cursor},
        )
        assert response.status_code == 422
        assert response.json() == {"detail": LIBRARY_CURSOR_INVALID}


def test_like_metacharacters_are_literal(alice: TestClient) -> None:
    resp = alice.get("/api/library/search", params={"q": "100%"})
    ids = [_hit_id(i) for i in resp.json()["items"]]
    assert ids == ["percent"]
    wildcard = alice.get("/api/library/search", params={"q": "100_"})
    assert wildcard.json()["items"] == []


def test_list_albums_q_and_sort(alice: TestClient) -> None:
    resp = alice.get(
        "/api/albums",
        params={"q": "nacht", "sort": LIBRARY_SORT_TITLE, "limit": 50},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_more"] is False
    assert data["total"] == 1
    assert data["items"][0]["id"] == "nachtstrom"

    empty = alice.get("/api/albums", params={"q": "   "})
    assert empty.status_code == 422
    assert empty.json()["detail"] == LIBRARY_QUERY_REQUIRED


def test_list_songs_q_and_sort(alice: TestClient) -> None:
    resp = alice.get(
        "/api/songs",
        params={"q": "remix", "sort": LIBRARY_SORT_NEWEST},
    )
    data = resp.json()
    assert data["total"] == 1
    assert data["has_more"] is False
    assert data["items"][0]["id"] == "song-nacht"
    assert data["items"][0]["album_title"] == "Nachtstrom"


def test_list_songs_without_album_id_excludes_archived_album_songs(tmp_path: Path) -> None:
    """GET /api/songs browse (no album_id) must hide songs of archived albums --
    both from items and from total/has_more, since count_songs and list_songs
    can drift independently if only one is filtered (#223 review finding)."""
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="visibility-live", title="Visibility Live",
            owner=USER_A, created_at=_ts(1),
        )
        _add_song(
            session, song_id="visibility-live-song", title="Visibility Case Song",
            album_id="visibility-live", created_at=_ts(2),
        )
        _add_album(
            session, album_id="visibility-archived", title="Visibility Archived",
            owner=USER_A, created_at=_ts(3), is_archived=True,
        )
        _add_song(
            session, song_id="visibility-archived-song", title="Visibility Case Song",
            album_id="visibility-archived", created_at=_ts(4),
        )
        session.commit()

    browse = client.get("/api/songs", params={"q": "Visibility Case Song"})
    data = browse.json()
    assert [s["id"] for s in data["items"]] == ["visibility-live-song"]
    assert data["total"] == 1
    assert data["has_more"] is False


def test_list_songs_with_album_id_shows_songs_of_an_archived_album(tmp_path: Path) -> None:
    """Direct-by-ID access (album_id set) must keep working for an archived
    album's songs -- AlbumDetailView depends on this (#223 review finding)."""
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="direct-archived", title="Direct Archived",
            owner=USER_A, created_at=_ts(1), is_archived=True,
        )
        _add_song(
            session, song_id="direct-archived-song", title="Direct Archived Song",
            album_id="direct-archived", created_at=_ts(2),
        )
        session.commit()

    scoped = client.get("/api/songs", params={"album_id": "direct-archived"})
    data = scoped.json()
    assert [s["id"] for s in data["items"]] == ["direct-archived-song"]
    assert data["total"] == 1


def test_list_albums_offset_pagination_stable_title_sort(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        for i in range(5):
            _add_album(
                session,
                album_id=f"alpha-{i}",
                title=f"Alpha {i}",
                owner=USER_A,
                created_at=_ts(i),
            )
        session.commit()

    first = client.get(
        "/api/albums",
        params={"q": "Alpha", "sort": LIBRARY_SORT_TITLE, "offset": 0, "limit": 2},
    ).json()
    second = client.get(
        "/api/albums",
        params={"q": "Alpha", "sort": LIBRARY_SORT_TITLE, "offset": 2, "limit": 2},
    ).json()
    third = client.get(
        "/api/albums",
        params={"q": "Alpha", "sort": LIBRARY_SORT_TITLE, "offset": 4, "limit": 2},
    ).json()
    ids = [a["id"] for a in first["items"] + second["items"] + third["items"]]
    assert ids == ["alpha-0", "alpha-1", "alpha-2", "alpha-3", "alpha-4"]
    assert first["has_more"] is True
    assert second["has_more"] is True
    assert third["has_more"] is False
    assert first["total"] == 5


def test_invalid_sort_is_rejected(alice: TestClient) -> None:
    assert alice.get("/api/albums", params={"sort": "popular"}).status_code == 422
    assert alice.get("/api/songs", params={"sort": "popular"}).status_code == 422
    assert alice.get(
        "/api/library/search", params={"q": "nacht", "sort": "popular"},
    ).status_code == 422


def test_oldest_sort_is_created_at_ascending(alice: TestClient) -> None:
    resp = alice.get(
        "/api/library/search",
        params={"q": "alice", "sort": LIBRARY_SORT_OLDEST},
    )
    ids = [_hit_id(i) for i in resp.json()["items"]]
    assert ids[0] == "alice-own"


def test_search_album_hit_includes_picked_count(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="picks-album", title="Picks Album",
            owner=USER_A, created_at=_ts(1),
        )
        _add_song(
            session, song_id="picks-picked", title="Picked Song",
            album_id="picks-album", created_at=_ts(2),
        )
        session.add(Generation(
            id="g-picked", song_id="picks-picked", generation_number=1,
            mp3_path=f"{USER_A}/g-picked.mp3", seed=1, is_picked=True,
        ))
        _add_song(
            session, song_id="picks-unpicked", title="Unpicked Song",
            album_id="picks-album", created_at=_ts(3),
        )
        session.commit()

    resp = client.get("/api/library/search", params={"q": "Picks Album"})
    assert resp.status_code == 200
    album_hit = next(
        item for item in resp.json()["items"]
        if item["type"] == LIBRARY_ITEM_ALBUM and item["album"]["id"] == "picks-album"
    )
    assert album_hit["album"]["picked_count"] == 1


def test_search_album_hit_excludes_archived_pick(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="archived-picks-album", title="Archived Picks Album",
            owner=USER_A, created_at=_ts(1),
        )
        _add_song(
            session, song_id="ap-song", title="Archived Pick Song",
            album_id="archived-picks-album", created_at=_ts(2),
        )
        session.add(Generation(
            id="g-archived-pick", song_id="ap-song", generation_number=1,
            mp3_path=f"{USER_A}/g-archived-pick.mp3", seed=1,
            is_picked=True, is_archived=True,
        ))
        session.commit()

    resp = client.get("/api/library/search", params={"q": "Archived Picks Album"})
    assert resp.status_code == 200
    album_hit = next(
        item for item in resp.json()["items"]
        if item["type"] == LIBRARY_ITEM_ALBUM and item["album"]["id"] == "archived-picks-album"
    )
    assert album_hit["album"]["picked_count"] == 0


def test_list_albums_excludes_archived_by_default(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="arch-hidden", title="Archived Album",
            owner=USER_A, created_at=_ts(1), is_archived=True,
        )
        session.commit()

    resp = client.get("/api/albums")
    ids = [a["id"] for a in resp.json()["items"]]
    assert "arch-hidden" not in ids


def test_list_albums_archived_filter_shows_only_archived(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="arch-visible", title="Archived Visible",
            owner=USER_A, created_at=_ts(1), is_archived=True,
        )
        session.commit()

    resp = client.get("/api/albums", params={"archived": "true"})
    ids = [a["id"] for a in resp.json()["items"]]
    assert ids == ["arch-visible"]
    assert "nachtstrom" not in ids


def test_search_excludes_archived_album(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="arch-search", title="Archived Search Album",
            owner=USER_A, created_at=_ts(1), is_archived=True,
        )
        session.commit()

    resp = client.get("/api/library/search", params={"q": "Archived Search Album"})
    assert resp.json()["items"] == []


def test_search_excludes_songs_of_archived_album(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="arch-song-parent", title="Archived Song Parent",
            owner=USER_A, created_at=_ts(1), is_archived=True,
        )
        _add_song(
            session, song_id="arch-song", title="Archived Child Song",
            album_id="arch-song-parent", created_at=_ts(2),
        )
        session.commit()

    resp = client.get("/api/library/search", params={"q": "Archived Child Song"})
    assert resp.json()["items"] == []


def test_pool_queue_excludes_generations_from_archived_albums(
    tmp_path: Path, monkeypatch,
) -> None:
    import songmaker_cli.queue_streams as queue_streams

    monkeypatch.setattr(queue_streams, "probe_audio_duration", lambda _path: 10.0)

    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="pool-live", title="Pool Live",
            owner=USER_A, created_at=_ts(1),
        )
        _add_song(
            session, song_id="pool-live-song", title="Live Song",
            album_id="pool-live", created_at=_ts(2),
        )
        session.add(Generation(
            id="g-pool-live", song_id="pool-live-song", generation_number=1,
            mp3_path=f"{USER_A}/g-pool-live.mp3", seed=1,
        ))
        _add_album(
            session, album_id="pool-archived", title="Pool Archived",
            owner=USER_A, created_at=_ts(3), is_archived=True,
        )
        _add_song(
            session, song_id="pool-archived-song", title="Archived Song",
            album_id="pool-archived", created_at=_ts(4),
        )
        session.add(Generation(
            id="g-pool-archived", song_id="pool-archived-song", generation_number=1,
            mp3_path=f"{USER_A}/g-pool-archived.mp3", seed=2,
        ))
        session.commit()

    audio_dir = tmp_path / "audio" / USER_A
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "g-pool-live.mp3").write_bytes(b"source")

    resp = client.get("/api/library/pool-queue", params={"pool": "all"})
    assert resp.status_code == 200
    take_ids = [t["generation_id"] for t in resp.json()["takes"]]
    assert take_ids == ["g-pool-live"]
