"""Tests for playlists — DB queries, API endpoints, sharing."""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import TEST_SECRET, login_and_csrf, make_fake_redis, make_test_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import event
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import slugify
from songmaker_cli.app_context import AppContext
from songmaker_cli.auth import hash_password
from songmaker_cli.constants import (
    COVER_JPEG_MAGIC,
    COVER_MAX_BYTES,
    COVER_PNG_EXTENSION,
    COVER_TOO_LARGE,
    COVER_UNSUPPORTED_TYPE,
    COVER_VARIANT_CARD,
    COVER_VARIANT_DETAIL,
    COVER_VARIANT_ORIGINAL,
    PLAYLIST_COVER_DIRNAME,
)
from songmaker_cli.covers import write_playlist_cover
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import (
    Album,
    Generation,
    Playlist,
    PlaylistEntry,
    Song,
    User,
    Version,
)
from songmaker_cli.db.queries import (
    add_album_to_playlist,
    add_generation_to_playlist,
    add_song_to_playlist,
    create_playlist,
    delete_playlist,
    disable_playlist_sharing,
    enable_playlist_sharing,
    get_generation,
    get_playlist,
    get_playlist_by_slug,
    list_playlists,
    remove_from_playlist,
    reorder_playlist_entry,
    set_playlist_cover_key,
    update_playlist,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

_DEFAULT_USER_ID = "u-test"


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 24), (40, 80, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def _create_playlist(session: Session, title: str, user_id: str = _DEFAULT_USER_ID) -> Playlist:
    """create_playlist() for these DB-query tests, which exercise the query
    function directly rather than through the API's unique_playlist_slug()
    reservation -- every title used below is unique within its own test, so
    a plain slugify() of the title is a real, non-colliding slug."""
    return create_playlist(session, title, user_id, slug=slugify(title))


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def db_factory(tmp_path: Path):
    return init_db(tmp_path / "test.db")


def _seed_test_data(session: Session) -> None:
    session.add(User(id=_DEFAULT_USER_ID, username="test", password_hash="x", role="user"))
    session.flush()
    session.add(Album(id="a1", title="Album One", artist="Artist", created_by=_DEFAULT_USER_ID))
    session.add(
        Song(id="s1", title="Song One", album_id="a1", track_number=1, slug="song-one"),
    )
    session.add(
        Song(id="s2", title="Song Two", album_id="a1", track_number=2, slug="song-two"),
    )
    session.flush()
    session.add(Version(id="v1", song_id="s1", version_number=1, lyrics="hi", prompt="rock"))
    session.add(Version(id="v2", song_id="s2", version_number=1, lyrics="hi", prompt="pop"))
    session.flush()
    session.add(Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="u-test/g1.mp3", seed=42, is_picked=True,
    ))
    session.add(Generation(
        id="g2", song_id="s1", version_id="v1", generation_number=2,
        mp3_path="u-test/g2.mp3", seed=99,
    ))
    session.add(Generation(
        id="g3", song_id="s2", version_id="v2", generation_number=1,
        mp3_path="u-test/g3.mp3", seed=77, is_picked=True,
    ))


@pytest.fixture
def seeded_session(db_factory) -> Session:
    session = db_factory()
    _seed_test_data(session)
    session.commit()
    yield session
    session.close()


def _fake_user():
    user = AuthenticatedUser(
        id=_DEFAULT_USER_ID, username="test", role="user", is_active=True,
    )
    return lambda: user


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        _seed_test_data(session)
        session.commit()

    audio_dir = tmp_path / "audio"
    owner_dir = audio_dir / "u-test"
    owner_dir.mkdir(parents=True)
    for name in ("g1.mp3", "g2.mp3", "g3.mp3"):
        (owner_dir / name).write_bytes(b"source")
    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router
    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user()
    app.include_router(router)
    yield TestClient(app)


# ── DB query tests ────────────────────────────────────────────────────


def test_create_and_list_playlists(seeded_session: Session) -> None:
    _create_playlist(seeded_session, "My Mix")
    _create_playlist(seeded_session, "Chill")
    seeded_session.commit()
    playlists = list_playlists(seeded_session, _DEFAULT_USER_ID)
    assert len(playlists) == 2
    assert {p.title for p in playlists} == {"Chill", "My Mix"}


def _add_album_generation(
    session: Session,
    *,
    album_id: str,
    song_id: str,
    generation_id: str,
    cover_key: str | None,
) -> None:
    session.add(Album(
        id=album_id,
        title=album_id,
        artist="Artist",
        created_by=_DEFAULT_USER_ID,
        cover_key=cover_key,
    ))
    session.add(Song(id=song_id, title=song_id, album_id=album_id, slug=song_id))
    session.add(Version(
        id=f"version-{song_id}", song_id=song_id, version_number=1, lyrics="lyrics",
    ))
    session.add(Generation(
        id=generation_id,
        song_id=song_id,
        version_id=f"version-{song_id}",
        generation_number=1,
        mp3_path=f"{_DEFAULT_USER_ID}/{generation_id}.mp3",
    ))


def test_list_playlists_collects_distinct_album_covers_in_entry_order_without_n_plus_one(
    seeded_session: Session,
) -> None:
    seeded_session.query(Album).filter_by(id="a1").update({"cover_key": "one.png"})
    _add_album_generation(
        seeded_session,
        album_id="a2",
        song_id="s3",
        generation_id="g4",
        cover_key="two.png",
    )
    _add_album_generation(
        seeded_session,
        album_id="a3",
        song_id="s4",
        generation_id="g5",
        cover_key="three.png",
    )
    playlist = _create_playlist(seeded_session, "Covers")
    seeded_session.add_all([
        PlaylistEntry(playlist_id=playlist.id, generation_id="g1", position=0),
        PlaylistEntry(playlist_id=playlist.id, generation_id="g2", position=1),
        PlaylistEntry(playlist_id=playlist.id, generation_id="g4", position=2),
        PlaylistEntry(playlist_id=playlist.id, generation_id="g5", position=3),
        PlaylistEntry(playlist_id=playlist.id, generation_id="g1", position=4),
    ])
    seeded_session.commit()
    seeded_session.expire_all()

    queries: list[str] = []

    def record_query(conn, cursor, statement, parameters, context, executemany) -> None:
        queries.append(statement)

    engine = seeded_session.get_bind()
    handle: Callable = record_query
    event.listen(engine, "before_cursor_execute", handle)
    try:
        playlists = list_playlists(seeded_session, _DEFAULT_USER_ID)
        response = next(item for item in playlists if item.id == playlist.id)
        from songmaker_cli.api_models.playlists import PlaylistResponse

        playlist_response = PlaylistResponse.from_orm(response)
    finally:
        event.remove(engine, "before_cursor_execute", handle)

    assert playlist_response.cover is None
    assert [cover.card for cover in playlist_response.album_covers] == [
        "/api/albums/a1/cover?variant=card&v=one.png",
        "/api/albums/a2/cover?variant=card&v=two.png",
        "/api/albums/a3/cover?variant=card&v=three.png",
    ]
    assert len(queries) == 1, (
        "expected one joined playlist query including entry album covers, "
        f"got {len(queries)}: {queries}"
    )


def test_playlist_response_reports_own_cover_beside_album_cover_mosaic(
    seeded_session: Session,
) -> None:
    seeded_session.query(Album).filter_by(id="a1").update({"cover_key": "album.png"})
    playlist = _create_playlist(seeded_session, "Own cover")
    add_generation_to_playlist(seeded_session, playlist.id, "g1")
    set_playlist_cover_key(seeded_session, playlist.id, "playlist.png")
    seeded_session.commit()

    loaded = get_playlist(seeded_session, playlist.id)
    assert loaded is not None
    from songmaker_cli.api_models.playlists import PlaylistResponse

    response = PlaylistResponse.from_orm(loaded)
    assert response.cover is not None
    assert response.cover.card == "/api/playlists/{}/cover?variant=card&v=playlist.png".format(
        playlist.id,
    )
    assert response.cover.detail == "/api/playlists/{}/cover?variant=detail&v=playlist.png".format(
        playlist.id,
    )
    assert [cover.card for cover in response.album_covers] == [
        "/api/albums/a1/cover?variant=card&v=album.png",
    ]


def test_playlist_response_omits_coverless_albums_and_limits_covers_to_four(
    seeded_session: Session,
) -> None:
    playlist = _create_playlist(seeded_session, "Four covers")
    generation_ids: list[str] = []
    for index in range(6):
        generation_id = f"cover-generation-{index}"
        generation_ids.append(generation_id)
        _add_album_generation(
            seeded_session,
            album_id=f"cover-album-{index}",
            song_id=f"cover-song-{index}",
            generation_id=generation_id,
            cover_key=None if index == 1 else f"cover-{index}.png",
        )
    seeded_session.flush()
    seeded_session.add_all([
        PlaylistEntry(playlist_id=playlist.id, generation_id=generation_id, position=index)
        for index, generation_id in enumerate(generation_ids)
    ])
    seeded_session.commit()

    loaded = get_playlist(seeded_session, playlist.id)
    assert loaded is not None
    from songmaker_cli.api_models.playlists import PlaylistResponse

    album_covers = PlaylistResponse.from_orm(loaded).album_covers
    assert [cover.card for cover in album_covers] == [
        "/api/albums/cover-album-0/cover?variant=card&v=cover-0.png",
        "/api/albums/cover-album-2/cover?variant=card&v=cover-2.png",
        "/api/albums/cover-album-3/cover?variant=card&v=cover-3.png",
        "/api/albums/cover-album-4/cover?variant=card&v=cover-4.png",
    ]


def test_get_playlist_with_entries(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    add_generation_to_playlist(seeded_session, playlist.id, "g1")
    seeded_session.commit()
    loaded = get_playlist(seeded_session, playlist.id)
    assert loaded is not None
    assert len(loaded.entries) == 1
    assert loaded.entries[0].generation.id == "g1"


def test_update_playlist(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Old")
    seeded_session.commit()
    updated = update_playlist(seeded_session, playlist.id, "New", slug=slugify("New"))
    seeded_session.commit()
    assert updated.title == "New"
    assert updated.slug == "new"


def test_delete_playlist(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Doomed")
    seeded_session.commit()
    delete_playlist(seeded_session, playlist.id)
    seeded_session.commit()
    assert get_playlist(seeded_session, playlist.id) is None


def test_delete_playlist_not_found(seeded_session: Session) -> None:
    with pytest.raises(ValueError, match="Playlist not found"):
        delete_playlist(seeded_session, "nonexistent")


def test_update_playlist_not_found(seeded_session: Session) -> None:
    with pytest.raises(ValueError, match="Playlist not found"):
        update_playlist(seeded_session, "nonexistent", "x", slug="x")


def test_add_generation_sets_is_kept(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    assert get_generation(seeded_session, "g2").is_kept is False
    add_generation_to_playlist(seeded_session, playlist.id, "g2")
    seeded_session.commit()
    assert get_generation(seeded_session, "g2").is_kept is True


def test_add_generation_not_found(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    seeded_session.commit()
    with pytest.raises(ValueError, match="Generation not found"):
        add_generation_to_playlist(seeded_session, playlist.id, "nonexistent")


def test_add_song_adds_picked_generation(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    entry = add_song_to_playlist(seeded_session, playlist.id, "s1")
    seeded_session.commit()
    assert entry is not None
    assert entry.generation_id == "g1"


def test_add_song_no_pick_uses_newest_playable(seeded_session: Session) -> None:
    seeded_session.query(Generation).filter_by(id="g3").update({"is_picked": False})
    seeded_session.commit()
    playlist = _create_playlist(seeded_session, "Test")
    result = add_song_to_playlist(seeded_session, playlist.id, "s2")
    assert result is not None
    assert result.generation_id == "g3"


def test_add_song_not_found(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    seeded_session.commit()
    with pytest.raises(ValueError, match="Song not found"):
        add_song_to_playlist(seeded_session, playlist.id, "nonexistent")


def test_add_album_adds_all_picked(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    result = add_album_to_playlist(seeded_session, playlist.id, "a1")
    seeded_session.commit()
    assert len(result.entries) == 2
    gen_ids = {e.generation_id for e in result.entries}
    assert gen_ids == {"g1", "g3"}
    assert result.skipped == []


def test_add_album_not_found(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    seeded_session.commit()
    with pytest.raises(ValueError, match="Album not found"):
        add_album_to_playlist(seeded_session, playlist.id, "nonexistent")


def test_remove_from_playlist(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    entry = add_generation_to_playlist(seeded_session, playlist.id, "g1")
    add_generation_to_playlist(seeded_session, playlist.id, "g2")
    seeded_session.commit()

    remove_from_playlist(seeded_session, playlist.id, entry.id)
    seeded_session.commit()

    loaded = get_playlist(seeded_session, playlist.id)
    assert len(loaded.entries) == 1
    assert loaded.entries[0].generation_id == "g2"
    assert loaded.entries[0].position == 0


def test_remove_from_playlist_not_found(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    seeded_session.commit()
    with pytest.raises(ValueError, match="Playlist entry not found"):
        remove_from_playlist(seeded_session, playlist.id, "nonexistent")


def test_reorder_playlist_entry_forward(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    e1 = add_generation_to_playlist(seeded_session, playlist.id, "g1")
    add_generation_to_playlist(seeded_session, playlist.id, "g2")
    add_generation_to_playlist(seeded_session, playlist.id, "g3")
    seeded_session.commit()

    reorder_playlist_entry(seeded_session, playlist.id, e1.id, 2)
    seeded_session.commit()

    loaded = get_playlist(seeded_session, playlist.id)
    positions = {e.generation_id: e.position for e in loaded.entries}
    assert positions["g2"] == 0
    assert positions["g3"] == 1
    assert positions["g1"] == 2


def test_reorder_playlist_entry_backward(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    add_generation_to_playlist(seeded_session, playlist.id, "g1")
    add_generation_to_playlist(seeded_session, playlist.id, "g2")
    e3 = add_generation_to_playlist(seeded_session, playlist.id, "g3")
    seeded_session.commit()

    reorder_playlist_entry(seeded_session, playlist.id, e3.id, 0)
    seeded_session.commit()

    loaded = get_playlist(seeded_session, playlist.id)
    positions = {e.generation_id: e.position for e in loaded.entries}
    assert positions["g3"] == 0
    assert positions["g1"] == 1
    assert positions["g2"] == 2


def test_reorder_same_position_noop(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    e1 = add_generation_to_playlist(seeded_session, playlist.id, "g1")
    seeded_session.commit()
    reorder_playlist_entry(seeded_session, playlist.id, e1.id, 0)
    seeded_session.commit()
    loaded = get_playlist(seeded_session, playlist.id)
    assert loaded.entries[0].position == 0


def test_reorder_entry_not_found(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    seeded_session.commit()
    with pytest.raises(ValueError, match="Playlist entry not found"):
        reorder_playlist_entry(seeded_session, playlist.id, "nonexistent", 0)


def test_enable_disable_playlist_sharing(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    seeded_session.commit()

    shared = enable_playlist_sharing(seeded_session, playlist.id)
    seeded_session.commit()
    assert shared.is_shared is True
    assert shared.share_slug is not None
    slug = shared.share_slug

    found = get_playlist_by_slug(seeded_session, slug)
    assert found is not None
    assert found.id == playlist.id

    disable_playlist_sharing(seeded_session, playlist.id)
    seeded_session.commit()
    assert get_playlist_by_slug(seeded_session, slug) is None


def test_enable_sharing_not_found(seeded_session: Session) -> None:
    with pytest.raises(ValueError, match="Playlist not found"):
        enable_playlist_sharing(seeded_session, "nonexistent")


def test_disable_sharing_not_found(seeded_session: Session) -> None:
    with pytest.raises(ValueError, match="Playlist not found"):
        disable_playlist_sharing(seeded_session, "nonexistent")


def test_cascade_delete_generation_removes_entry(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    add_generation_to_playlist(seeded_session, playlist.id, "g2")
    seeded_session.commit()

    gen = seeded_session.query(Generation).filter_by(id="g2").first()
    seeded_session.delete(gen)
    seeded_session.commit()

    loaded = get_playlist(seeded_session, playlist.id)
    assert len(loaded.entries) == 0


def test_multiple_gens_same_song_allowed(seeded_session: Session) -> None:
    playlist = _create_playlist(seeded_session, "Test")
    add_generation_to_playlist(seeded_session, playlist.id, "g1")
    add_generation_to_playlist(seeded_session, playlist.id, "g2")
    seeded_session.commit()
    loaded = get_playlist(seeded_session, playlist.id)
    assert len(loaded.entries) == 2


# ── API endpoint tests ────────────────────────────────────────────────


def test_api_create_and_list_playlists(client: TestClient) -> None:
    resp = client.post("/api/playlists", json={"title": "My Mix"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "My Mix"
    assert data["slug"] == "my-mix"
    assert data["entry_count"] == 0

    resp = client.get("/api/playlists")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["slug"] == "my-mix"
    assert resp.json()[0]["album_covers"] == []


def test_api_create_playlist_dedupes_a_colliding_title(client: TestClient) -> None:
    first = client.post("/api/playlists", json={"title": "Favorites"})
    second = client.post("/api/playlists", json={"title": "Favorites"})

    assert first.json()["slug"] == "favorites"
    assert second.json()["slug"] == "favorites-2"


def test_api_get_playlist(client: TestClient) -> None:
    resp = client.post("/api/playlists", json={"title": "Detail"})
    pid = resp.json()["id"]

    resp = client.get(f"/api/playlists/{pid}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Detail"
    assert resp.json()["entries"] == []


def test_api_uploads_playlist_cover_variants_and_remove_restores_mosaic(
    client: TestClient, tmp_path: Path,
) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        album = session.query(Album).filter_by(id="a1").one()
        album.cover_key = "album.png"
        session.commit()

    created = client.post("/api/playlists", json={"title": "Covers"})
    playlist_id = created.json()["id"]
    client.post(
        f"/api/playlists/{playlist_id}/entries/generation",
        json={"generation_id": "g1"},
    )
    before_upload = client.get(f"/api/playlists/{playlist_id}")
    assert before_upload.json()["cover"] is None
    assert before_upload.json()["album_covers"] == [{
        "card": "/api/albums/a1/cover?variant=card&v=album.png",
        "detail": "/api/albums/a1/cover?variant=detail&v=album.png",
    }]

    uploaded = client.put(
        f"/api/playlists/{playlist_id}/cover",
        files={"file": ("cover.png", _png_bytes(), "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    cover = uploaded.json()["cover"]
    assert cover is not None
    cover_dir = tmp_path / "audio" / PLAYLIST_COVER_DIRNAME / playlist_id
    assert (cover_dir / f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}").is_file()
    assert (cover_dir / f"{COVER_VARIANT_CARD}.jpg").is_file()
    assert (cover_dir / f"{COVER_VARIANT_DETAIL}.jpg").is_file()
    assert client.get(cover["card"]).headers["content-type"].startswith("image/jpeg")
    assert client.get(cover["detail"]).status_code == 200
    assert client.get(
        f"/api/playlists/{playlist_id}/cover?variant={COVER_VARIANT_ORIGINAL}",
    ).headers["content-type"].startswith("image/png")

    deleted = client.delete(f"/api/playlists/{playlist_id}/cover")
    assert deleted.status_code == 200
    assert deleted.json()["cover"] is None
    assert deleted.json()["album_covers"] == before_upload.json()["album_covers"]
    assert not cover_dir.exists()
    assert client.get(cover["detail"]).status_code == 404


@pytest.mark.parametrize(
    ("payload", "media_type", "status_code", "detail"),
    [
        (b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "image/svg+xml", 422,
         COVER_UNSUPPORTED_TYPE),
        (COVER_JPEG_MAGIC + b"\\x00" * COVER_MAX_BYTES, "image/jpeg", 413,
         COVER_TOO_LARGE),
    ],
)
def test_api_rejects_invalid_playlist_covers(
    client: TestClient, payload: bytes, media_type: str, status_code: int, detail: str,
) -> None:
    playlist_id = client.post("/api/playlists", json={"title": "Rejected"}).json()["id"]

    response = client.put(
        f"/api/playlists/{playlist_id}/cover",
        files={"file": ("cover", payload, media_type)},
    )

    assert response.status_code == status_code
    assert response.json()["detail"] == detail
    assert client.get(f"/api/playlists/{playlist_id}").json()["cover"] is None


def test_foreign_playlist_cover_routes_are_not_found(client: TestClient) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        session.add(User(id="foreign-user", username="foreign", password_hash="x", role="user"))
        session.flush()
        session.add(Playlist(
            id="foreign-playlist", title="Foreign", slug="foreign", created_by="foreign-user",
        ))
        session.commit()

    path = "/api/playlists/foreign-playlist/cover"
    assert client.get(path).status_code == 404
    assert client.put(
        path, files={"file": ("cover.png", _png_bytes(), "image/png")},
    ).status_code == 404
    assert client.delete(path).status_code == 404


def test_api_update_playlist(client: TestClient) -> None:
    resp = client.post("/api/playlists", json={"title": "Old"})
    pid = resp.json()["id"]

    resp = client.put(f"/api/playlists/{pid}", json={"title": "New"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "New"
    assert resp.json()["slug"] == "new"


def test_api_rename_playlist_to_its_own_title_keeps_its_slug(client: TestClient) -> None:
    resp = client.post("/api/playlists", json={"title": "Steady"})
    pid = resp.json()["id"]

    resp = client.put(f"/api/playlists/{pid}", json={"title": "Steady"})
    assert resp.status_code == 200
    assert resp.json()["slug"] == "steady"


def test_api_delete_playlist(client: TestClient) -> None:
    resp = client.post("/api/playlists", json={"title": "Doomed"})
    pid = resp.json()["id"]

    resp = client.delete(f"/api/playlists/{pid}")
    assert resp.status_code == 200

    resp = client.get(f"/api/playlists/{pid}")
    assert resp.status_code == 404


def test_api_delete_playlist_removes_its_cover_after_commit(
    client: TestClient,
) -> None:
    playlist_id = client.post("/api/playlists", json={"title": "Doomed"}).json()["id"]
    cover_dir = client.app.state.ctx.audio_dir / PLAYLIST_COVER_DIRNAME / playlist_id
    write_playlist_cover(client.app.state.ctx.audio_dir, playlist_id, _png_bytes())

    response = client.delete(f"/api/playlists/{playlist_id}")

    assert response.status_code == 200
    assert not cover_dir.exists()


def test_api_delete_playlist_keeps_its_cover_when_commit_fails(
    client: TestClient,
) -> None:
    playlist_id = client.post("/api/playlists", json={"title": "Doomed"}).json()["id"]
    cover_dir = client.app.state.ctx.audio_dir / PLAYLIST_COVER_DIRNAME / playlist_id
    write_playlist_cover(client.app.state.ctx.audio_dir, playlist_id, _png_bytes())

    with patch(
        "songmaker_cli.playlist_api.Session.commit",
        side_effect=RuntimeError("commit failed"),
    ):
        with pytest.raises(RuntimeError, match="commit failed"):
            client.delete(f"/api/playlists/{playlist_id}")

    assert cover_dir.is_dir()


def test_api_add_generation_to_playlist(client: TestClient) -> None:
    resp = client.post("/api/playlists", json={"title": "Test"})
    pid = resp.json()["id"]

    resp = client.post(
        f"/api/playlists/{pid}/entries/generation",
        json={"generation_id": "g1"},
    )
    assert resp.status_code == 200
    assert resp.json()["generation_id"] == "g1"
    assert resp.json()["lyrics"] == "hi"
    assert resp.json()["is_picked"] is True
    assert resp.json()["version_number"] == 1

    resp = client.get(f"/api/playlists/{pid}")
    entries = resp.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["lyrics"] == "hi"
    assert entries[0]["album_title"] == "Album One"
    assert entries[0]["is_picked"] is True
    assert entries[0]["version_number"] == 1
    # audio_duration is the take's own measured length (#258), never the
    # requested parameter -- unmeasured is None here, not 0.
    assert entries[0]["audio_duration"] is None


def test_playlist_entry_reports_the_takes_measured_duration(client: TestClient) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        gen = session.query(Generation).filter_by(id="g1").one()
        gen.audio_duration_sec = 141.0
        session.commit()

    resp = client.post("/api/playlists", json={"title": "Test"})
    pid = resp.json()["id"]
    client.post(f"/api/playlists/{pid}/entries/generation", json={"generation_id": "g1"})

    resp = client.get(f"/api/playlists/{pid}")
    assert resp.json()["entries"][0]["audio_duration"] == 141.0


def test_api_add_song_to_playlist(client: TestClient) -> None:
    resp = client.post("/api/playlists", json={"title": "Test"})
    pid = resp.json()["id"]

    resp = client.post(
        f"/api/playlists/{pid}/entries/song", json={"song_id": "s1"},
    )
    assert resp.status_code == 200

    resp = client.get(f"/api/playlists/{pid}")
    entries = resp.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["generation_id"] == "g1"
    assert entries[0]["song_id"] == "s1"


def test_api_add_album_to_playlist(client: TestClient) -> None:
    resp = client.post("/api/playlists", json={"title": "Test"})
    pid = resp.json()["id"]

    resp = client.post(
        f"/api/playlists/{pid}/entries/album", json={"album_id": "a1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["added_count"] == 2
    assert body["skipped"] == []

    resp = client.get(f"/api/playlists/{pid}")
    assert len(resp.json()["entries"]) == 2


def test_api_add_album_to_playlist_hides_missing_and_foreign_albums(client: TestClient) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        session.add(User(id="foreign-user", username="foreign", password_hash="x", role="user"))
        session.flush()
        session.add(
            Album(
                id="foreign-album",
                title="Foreign",
                artist="Other",
                created_by="foreign-user",
            ),
        )
        session.commit()

    playlist_id = client.post("/api/playlists", json={"title": "Test"}).json()["id"]
    for album_id in ("missing-album", "foreign-album"):
        response = client.post(
            f"/api/playlists/{playlist_id}/entries/album",
            json={"album_id": album_id},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Album not found"


def test_api_remove_entry(client: TestClient) -> None:
    resp = client.post("/api/playlists", json={"title": "Test"})
    pid = resp.json()["id"]
    client.post(f"/api/playlists/{pid}/entries/generation", json={"generation_id": "g1"})
    client.post(f"/api/playlists/{pid}/entries/generation", json={"generation_id": "g2"})

    resp = client.get(f"/api/playlists/{pid}")
    entry_id = resp.json()["entries"][0]["id"]

    resp = client.delete(f"/api/playlists/{pid}/entries/{entry_id}")
    assert resp.status_code == 200

    resp = client.get(f"/api/playlists/{pid}")
    assert len(resp.json()["entries"]) == 1


def test_api_reorder_entry(client: TestClient) -> None:
    resp = client.post("/api/playlists", json={"title": "Test"})
    pid = resp.json()["id"]
    client.post(f"/api/playlists/{pid}/entries/generation", json={"generation_id": "g1"})
    client.post(f"/api/playlists/{pid}/entries/generation", json={"generation_id": "g2"})

    resp = client.get(f"/api/playlists/{pid}")
    first_entry_id = resp.json()["entries"][0]["id"]

    resp = client.patch(
        f"/api/playlists/{pid}/entries/{first_entry_id}/position",
        json={"new_position": 1},
    )
    assert resp.status_code == 200

    resp = client.get(f"/api/playlists/{pid}")
    entries = resp.json()["entries"]
    assert entries[0]["generation_id"] == "g2"
    assert entries[1]["generation_id"] == "g1"


def test_api_playlist_not_found(client: TestClient) -> None:
    assert client.get("/api/playlists/nonexistent").status_code == 404
    assert client.put("/api/playlists/nonexistent", json={"title": "x"}).status_code == 404
    assert client.delete("/api/playlists/nonexistent").status_code == 404


def test_api_entry_not_found(client: TestClient) -> None:
    resp = client.post("/api/playlists", json={"title": "Test"})
    pid = resp.json()["id"]
    assert client.delete(f"/api/playlists/{pid}/entries/nonexistent").status_code == 404
    resp = client.patch(
        f"/api/playlists/{pid}/entries/nonexistent/position",
        json={"new_position": 0},
    )
    assert resp.status_code == 404


def test_api_add_song_no_pick_uses_newest_playable(client: TestClient) -> None:
    resp = client.post("/api/playlists", json={"title": "Test"})
    pid = resp.json()["id"]
    client.post("/api/generations/g3/unpick")
    resp = client.post(f"/api/playlists/{pid}/entries/song", json={"song_id": "s2"})
    assert resp.status_code == 200
    detail = client.get(f"/api/playlists/{pid}")
    assert detail.json()["entries"][0]["generation_id"] == "g3"


def test_add_song_archived_only_returns_none(seeded_session: Session) -> None:
    seeded_session.query(Generation).filter_by(id="g3").update(
        {"is_archived": True, "is_picked": False}
    )
    seeded_session.commit()
    playlist = _create_playlist(seeded_session, "Test")
    result = add_song_to_playlist(seeded_session, playlist.id, "s2")
    assert result is None


def test_api_add_nonexistent_generation(client: TestClient) -> None:
    resp = client.post("/api/playlists", json={"title": "Test"})
    pid = resp.json()["id"]
    resp = client.post(
        f"/api/playlists/{pid}/entries/generation",
        json={"generation_id": "nonexistent"},
    )
    assert resp.status_code == 404


# ── Sharing API tests ─────────────────────────────────────────────────


def _seed_sharing_data(session) -> None:
    admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
    session.add(admin)
    session.add(Album(id="a1", title="Album", artist="Artist"))
    session.add(
        Song(id="s1", title="Song One", album_id="a1", track_number=1, slug="song-one"),
    )
    session.add(Version(id="v1", song_id="s1", version_number=1, lyrics="hi"))
    session.add(Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="admin_user/g1.mp3", seed=42, is_picked=True,
    ))
    playlist = Playlist(id="pl1", title="Shared Mix", slug="shared-mix", created_by=admin.id)
    session.add(playlist)
    session.add(PlaylistEntry(
        id="pe1", playlist_id="pl1", generation_id="g1", position=0,
    ))


def test_shared_playlist_view(tmp_path: Path) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_sharing_data)
    login_and_csrf(client, "admin", "admin12345")

    audio_dir = tmp_path / "audio" / "admin_user"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "g1.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)

    resp = client.post("/api/playlists/pl1/share")
    assert resp.status_code == 200
    slug = resp.json()["share_slug"]

    unauthed = TestClient(client.app, cookies={})
    resp = unauthed.get(f"/shared/playlist/{slug}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Shared Mix"
    assert len(data["entries"]) == 1
    assert data["entries"][0]["entry_id"] == "pe1"
    assert data["entries"][0]["song_title"] == "Song One"
    assert data["entries"][0]["audio_url"] is not None


def test_shared_playlist_audio(tmp_path: Path) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_sharing_data)
    login_and_csrf(client, "admin", "admin12345")

    audio_dir = tmp_path / "audio" / "admin_user"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "g1.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)

    resp = client.post("/api/playlists/pl1/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(client.app, cookies={})
    resp = unauthed.get(f"/shared/playlist/{slug}/audio/admin_user/g1.mp3")
    assert resp.status_code == 200


def test_shared_playlist_not_found(tmp_path: Path) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_sharing_data)
    unauthed = TestClient(client.app, cookies={})
    resp = unauthed.get("/shared/playlist/nonexistent-slug")
    assert resp.status_code == 404


def test_shared_playlist_audio_wrong_file(tmp_path: Path) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_sharing_data)
    login_and_csrf(client, "admin", "admin12345")

    resp = client.post("/api/playlists/pl1/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(client.app, cookies={})
    resp = unauthed.get(f"/shared/playlist/{slug}/audio/wrong.mp3")
    assert resp.status_code == 404


def test_unshare_playlist(tmp_path: Path) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_sharing_data)
    login_and_csrf(client, "admin", "admin12345")

    client.post("/api/playlists/pl1/share")
    resp = client.delete("/api/playlists/pl1/share")
    assert resp.status_code == 200


def test_playlist_response_logs_warning_when_entries_is_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`Playlist.entries` should never be None — SQLAlchemy returns []
    for an empty one-to-many. If it ever IS None, that's an ORM bug; W3
    requires it surface as a warning, not a silent fallback."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from songmaker_cli.api_models.playlists import PlaylistResponse

    fake_playlist = SimpleNamespace(
        id="pl-broken", title="T", slug="t", entries=None,
        is_shared=False, share_slug=None, cover_key=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with caplog.at_level("WARNING", logger="songmaker_cli.api_models.playlists"):
        resp = PlaylistResponse.from_orm(fake_playlist)
    assert resp.entry_count == 0
    assert any("entries=None" in r.message for r in caplog.records)
