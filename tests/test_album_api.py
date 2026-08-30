"""Album API tests — picked_count on AlbumResponse (#141 blocker 2b).

The album wall previously computed "picks" client-side from whatever songs
happened to be loaded, showing 0 picks for every album. picked_count is now
computed server-side, once per request, from the DB.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import login_and_csrf, make_test_app
from sqlalchemy import event

from songmaker_cli.auth import hash_password
from songmaker_cli.db.models import Album, AuditLog, Generation, Song, User, Version

_ADMIN_USER = "admin"
_ADMIN_PASSWORD = "admin12345"


def _count_queries(engine, *substrings: str) -> tuple[list[str], Callable]:
    """Register a query-count probe; caller removes it via the returned handle."""
    queries: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany) -> None:
        lowered = statement.lower()
        if all(s.lower() in lowered for s in substrings):
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    return queries, _record


def _add_song_with_generation(
    session,
    *,
    song_id: str,
    album_id: str,
    is_picked: bool = False,
    is_archived: bool = False,
) -> None:
    session.add(
        Song(id=song_id, title=song_id, album_id=album_id, track_number=1, slug=song_id),
    )
    session.add(Version(id=f"v-{song_id}", song_id=song_id, version_number=1, lyrics="l"))
    session.add(Generation(
        id=f"g-{song_id}", song_id=song_id, version_id=f"v-{song_id}",
        generation_number=1, mp3_path=f"{_ADMIN_USER}/{song_id}.mp3", seed=1,
        is_picked=is_picked, is_archived=is_archived,
    ))


def _seed_pick_scenarios(session) -> None:
    session.add(User(
        username=_ADMIN_USER, password_hash=hash_password(_ADMIN_PASSWORD), role="admin",
    ))

    session.add(Album(id="no-songs", title="No Songs", artist="A"))

    session.add(Album(id="one-pick", title="One Pick", artist="A"))
    _add_song_with_generation(session, song_id="op-picked", album_id="one-pick", is_picked=True)
    _add_song_with_generation(session, song_id="op-unpicked", album_id="one-pick")

    session.add(Album(id="many-picks", title="Many Picks", artist="A"))
    for i in range(3):
        _add_song_with_generation(
            session, song_id=f"mp-picked-{i}", album_id="many-picks", is_picked=True,
        )
    _add_song_with_generation(
        session, song_id="mp-archived-pick", album_id="many-picks",
        is_picked=True, is_archived=True,
    )


@pytest.fixture()
def picks_client(tmp_path: Path):
    client, factory = make_test_app(tmp_path, seed_db=_seed_pick_scenarios)
    login_and_csrf(client, _ADMIN_USER, _ADMIN_PASSWORD)
    return client, factory


def test_list_albums_picked_count_zero_when_no_picks(picks_client) -> None:
    client, _ = picks_client
    resp = client.get("/api/albums")
    assert resp.status_code == 200
    by_id = {a["id"]: a for a in resp.json()["items"]}
    assert by_id["no-songs"]["picked_count"] == 0


def test_list_albums_picked_count_counts_one_picked_song(picks_client) -> None:
    client, _ = picks_client
    resp = client.get("/api/albums")
    by_id = {a["id"]: a for a in resp.json()["items"]}
    assert by_id["one-pick"]["picked_count"] == 1


def test_list_albums_picked_count_counts_n_picked_songs(picks_client) -> None:
    client, _ = picks_client
    resp = client.get("/api/albums")
    by_id = {a["id"]: a for a in resp.json()["items"]}
    assert by_id["many-picks"]["picked_count"] == 3


def test_list_albums_picked_count_excludes_archived_pick(picks_client) -> None:
    client, _ = picks_client
    resp = client.get("/api/albums")
    by_id = {a["id"]: a for a in resp.json()["items"]}
    # 3 active picks + 1 archived pick on a 4th song — archived one must not count.
    assert by_id["many-picks"]["picked_count"] == 3


def test_get_album_returns_picked_count(picks_client) -> None:
    client, _ = picks_client
    resp = client.get("/api/albums/one-pick")
    assert resp.status_code == 200
    assert resp.json()["picked_count"] == 1


def test_list_albums_computes_picked_count_in_one_aggregate_query(picks_client) -> None:
    client, factory = picks_client
    with factory() as probe_session:
        engine = probe_session.get_bind()

    queries, handle = _count_queries(engine, "from songs", "join generations")
    try:
        resp = client.get("/api/albums")
    finally:
        event.remove(engine, "before_cursor_execute", handle)

    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 3
    assert len(queries) == 1, (
        f"expected one aggregate pick-count query for all albums, got {len(queries)}: {queries}"
    )


def _seed_metadata_scenarios(session) -> None:
    session.add(User(
        username=_ADMIN_USER, password_hash=hash_password(_ADMIN_PASSWORD), role="admin",
    ))
    session.add(Album(
        id="meta-album", title="Meta Album", artist="A",
        subtitle="Old Subtitle", year="1999",
    ))


@pytest.fixture()
def metadata_client(tmp_path: Path):
    client, factory = make_test_app(tmp_path, seed_db=_seed_metadata_scenarios)
    login_and_csrf(client, _ADMIN_USER, _ADMIN_PASSWORD)
    return client, factory


def test_update_album_subtitle(metadata_client) -> None:
    client, _ = metadata_client
    resp = client.put("/api/albums/meta-album", json={"subtitle": "Live at the Roxy"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["subtitle"] == "Live at the Roxy"
    assert body["title"] == "Meta Album"
    assert body["year"] == "1999"


def test_update_album_subtitle_empty_clears(metadata_client) -> None:
    client, _ = metadata_client
    resp = client.put("/api/albums/meta-album", json={"subtitle": ""})
    assert resp.status_code == 200
    assert resp.json()["subtitle"] == ""


def test_update_album_year(metadata_client) -> None:
    client, _ = metadata_client
    resp = client.put("/api/albums/meta-album", json={"year": 2010})
    assert resp.status_code == 200
    body = resp.json()
    assert body["year"] == "2010"
    assert body["subtitle"] == "Old Subtitle"


def test_update_album_year_below_range_rejected(metadata_client) -> None:
    client, _ = metadata_client
    resp = client.put("/api/albums/meta-album", json={"year": 1899})
    assert resp.status_code == 422
    after = client.get("/api/albums/meta-album")
    assert after.json()["year"] == "1999"


def test_update_album_year_above_range_rejected(metadata_client) -> None:
    client, _ = metadata_client
    resp = client.put("/api/albums/meta-album", json={"year": 2101})
    assert resp.status_code == 422


def test_update_album_fields_are_independent(metadata_client) -> None:
    client, _ = metadata_client
    resp = client.put("/api/albums/meta-album", json={"subtitle": "New Sub"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Meta Album"
    assert body["year"] == "1999"


def test_update_album_no_fields_leaves_metadata_unchanged(metadata_client) -> None:
    client, _ = metadata_client
    resp = client.put("/api/albums/meta-album", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Meta Album"
    assert body["subtitle"] == "Old Subtitle"
    assert body["year"] == "1999"


def test_update_album_no_fields_writes_no_audit_row(metadata_client) -> None:
    client, factory = metadata_client
    resp = client.put("/api/albums/meta-album", json={})
    assert resp.status_code == 200
    with factory() as session:
        assert session.query(AuditLog).filter_by(resource_id="meta-album").count() == 0


def test_update_album_metadata_other_user_blocked(tmp_path: Path) -> None:
    def _seed(session) -> None:
        session.add(User(
            id="u-owner", username="owner", password_hash=hash_password("owner12345"),
            role="user",
        ))
        session.add(User(
            id="u-intruder", username="intruder", password_hash=hash_password("intruder12345"),
            role="user",
        ))
        session.flush()
        session.add(Album(
            id="theirs", title="Theirs", artist="A", created_by="u-owner",
            subtitle="Untouched",
        ))

    client, factory = make_test_app(tmp_path, seed_db=_seed)
    login_and_csrf(client, "intruder", "intruder12345")
    resp = client.put("/api/albums/theirs", json={"subtitle": "Hijacked"})
    assert resp.status_code == 404
    with factory() as session:
        assert session.query(Album).filter_by(id="theirs").first().subtitle == "Untouched"


def _seed_archive_scenarios(session) -> None:
    session.add(User(
        username=_ADMIN_USER, password_hash=hash_password(_ADMIN_PASSWORD), role="admin",
    ))
    session.add(Album(id="live-one", title="Live One", artist="A"))
    session.add(Album(id="live-two", title="Live Two", artist="A"))
    session.add(Album(id="already-archived", title="Already Archived", artist="A"))


@pytest.fixture()
def archive_client(tmp_path: Path):
    client, factory = make_test_app(tmp_path, seed_db=_seed_archive_scenarios)
    login_and_csrf(client, _ADMIN_USER, _ADMIN_PASSWORD)
    return client, factory


def test_archive_album_sets_is_archived_and_archived_at(archive_client) -> None:
    client, _ = archive_client
    resp = client.post("/api/albums/live-one/archive")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_archived"] is True
    assert body["archived_at"] is not None


def test_archive_album_disappears_from_default_list(archive_client) -> None:
    client, _ = archive_client
    client.post("/api/albums/live-one/archive")
    resp = client.get("/api/albums")
    ids = [a["id"] for a in resp.json()["items"]]
    assert "live-one" not in ids
    assert "live-two" in ids


def test_archived_filter_shows_only_archived_albums(archive_client) -> None:
    client, _ = archive_client
    client.post("/api/albums/live-one/archive")
    resp = client.get("/api/albums", params={"archived": "true"})
    ids = [a["id"] for a in resp.json()["items"]]
    assert ids == ["live-one"]


def test_unarchive_album_restores_default_visibility(archive_client) -> None:
    client, _ = archive_client
    client.post("/api/albums/live-one/archive")
    resp = client.post("/api/albums/live-one/unarchive")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_archived"] is False
    assert body["archived_at"] is None
    ids = [a["id"] for a in client.get("/api/albums").json()["items"]]
    assert "live-one" in ids


def test_archive_album_reachable_directly_by_id(archive_client) -> None:
    client, _ = archive_client
    client.post("/api/albums/live-one/archive")
    resp = client.get("/api/albums/live-one")
    assert resp.status_code == 200
    assert resp.json()["is_archived"] is True


def test_archive_album_writes_audit_row(archive_client) -> None:
    client, factory = archive_client
    client.post("/api/albums/live-one/archive")
    with factory() as session:
        rows = session.query(AuditLog).filter_by(resource_id="live-one", action="archive").all()
        assert len(rows) == 1


def test_archive_other_users_album_is_404(tmp_path: Path) -> None:
    def _seed(session) -> None:
        session.add(User(
            id="u-owner", username="owner", password_hash=hash_password("owner12345"),
            role="user",
        ))
        session.add(User(
            id="u-intruder", username="intruder", password_hash=hash_password("intruder12345"),
            role="user",
        ))
        session.flush()
        session.add(Album(id="theirs", title="Theirs", artist="A", created_by="u-owner"))

    client, factory = make_test_app(tmp_path, seed_db=_seed)
    login_and_csrf(client, "intruder", "intruder12345")
    resp = client.post("/api/albums/theirs/archive")
    assert resp.status_code == 404
    with factory() as session:
        assert session.query(Album).filter_by(id="theirs").first().is_archived is False


def test_unarchive_other_users_album_is_404(tmp_path: Path) -> None:
    def _seed(session) -> None:
        session.add(User(
            id="u-owner", username="owner", password_hash=hash_password("owner12345"),
            role="user",
        ))
        session.add(User(
            id="u-intruder", username="intruder", password_hash=hash_password("intruder12345"),
            role="user",
        ))
        session.flush()
        session.add(Album(
            id="theirs", title="Theirs", artist="A", created_by="u-owner", is_archived=True,
        ))

    client, factory = make_test_app(tmp_path, seed_db=_seed)
    login_and_csrf(client, "intruder", "intruder12345")
    resp = client.post("/api/albums/theirs/unarchive")
    assert resp.status_code == 404
    with factory() as session:
        assert session.query(Album).filter_by(id="theirs").first().is_archived is True


def test_archived_albums_share_link_stays_functional(archive_client) -> None:
    client, factory = archive_client
    share_resp = client.post("/api/albums/live-one/share")
    assert share_resp.status_code == 200
    slug = share_resp.json()["share_slug"]

    archive_resp = client.post("/api/albums/live-one/archive")
    assert archive_resp.status_code == 200

    public_resp = client.get(f"/shared/{slug}")
    assert public_resp.status_code == 200
