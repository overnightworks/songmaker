"""Personal library index — search, browse filters, ownership, keyset pagination."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import TEST_SECRET, make_fake_redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import (
    LIBRARY_CURSOR_INVALID,
    LIBRARY_CURSOR_MISMATCH,
    LIBRARY_ITEM_ALBUM,
    LIBRARY_ITEM_SONG,
    LIBRARY_QUERY_REQUIRED,
    LIBRARY_SORT_NEWEST,
    LIBRARY_SORT_OLDEST,
    LIBRARY_SORT_TITLE,
)
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Generation, Song, User, Version
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

USER_A = "user-a"
USER_B = "user-b"
ADMIN_ID = "user-admin"


def _fake_user(user_id: str, username: str, role: str):
    user = AuthenticatedUser(id=user_id, username=username, role=role, is_active=True)
    return lambda: user


def _ts(offset_seconds: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)


def _add_album(
    session, *, album_id: str, title: str, owner: str, created_at: datetime,
) -> Album:
    album = Album(
        id=album_id, title=title, artist="Artist",
        created_by=owner, created_at=created_at,
    )
    session.add(album)
    return album


def _add_song(
    session, *, song_id: str, title: str, album_id: str, created_at: datetime,
    track_number: int = 1,
) -> Song:
    song = Song(
        id=song_id, title=title, album_id=album_id,
        track_number=track_number, created_at=created_at,
    )
    session.add(song)
    session.add(Version(
        song_id=song_id, version_number=1, lyrics="lyrics", prompt="prompt",
    ))
    return song


def _library_env(tmp_path: Path) -> tuple[object, object]:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id=USER_A, username="alice", password_hash="unused", role="user",
        ))
        session.add(User(
            id=USER_B, username="bob", password_hash="unused", role="user",
        ))
        session.add(User(
            id=ADMIN_ID, username="admin", password_hash="unused", role="admin",
        ))
        session.flush()
        _seed_library(session)
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    return factory, ctx


def _client_for(ctx: object, user_id: str, role: str = "user") -> TestClient:
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user(
        user_id, f"test-{user_id}", role,
    )
    app.include_router(router)
    return TestClient(app)


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


@pytest.fixture()
def library_ctx(tmp_path: Path) -> tuple[object, object]:
    return _library_env(tmp_path)


@pytest.fixture()
def alice(library_ctx: tuple[object, object]) -> TestClient:
    _factory, ctx = library_ctx
    return _client_for(ctx, USER_A)


@pytest.fixture()
def bob(library_ctx: tuple[object, object]) -> TestClient:
    _factory, ctx = library_ctx
    return _client_for(ctx, USER_B)


@pytest.fixture()
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


def test_admin_browse_sees_all_search_stays_personal(admin: TestClient) -> None:
    albums = {a["id"] for a in admin.get("/api/albums").json()["items"]}
    assert "admin-own" in albums
    assert "nachtstrom" in albums
    hits = admin.get("/api/library/search", params={"q": "nachtstrom"}).json()["items"]
    assert hits == []
    own = admin.get("/api/library/search", params={"q": "admin"}).json()["items"]
    assert [(i["type"], _hit_id(i)) for i in own] == [(LIBRARY_ITEM_ALBUM, "admin-own")]


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

    tampered = alice.get(
        "/api/library/search",
        params={"q": "nachtstrom", "cursor": cursor[:-1] + ("0" if cursor[-1] != "0" else "1")},
    )
    assert tampered.status_code == 422
    assert tampered.json()["detail"] == LIBRARY_CURSOR_INVALID

    garbage = alice.get(
        "/api/library/search",
        params={"q": "nachtstrom", "cursor": "not-a-cursor"},
    )
    assert garbage.status_code == 422
    assert garbage.json()["detail"] == LIBRARY_CURSOR_INVALID


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
