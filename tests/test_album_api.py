"""Album API tests — picked_count on AlbumResponse (#141 blocker 2b).

The album wall previously computed "picks" client-side from whatever songs
happened to be loaded, showing 0 picks for every album. picked_count is now
computed server-side, once per request, from the DB.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import event
from support.route_budget import queries_without_session_auth
from support.web_app import make_test_app, seed_session

from songmaker_cli.db.models import (
    ALBUM_SLUG_MAX_LENGTH,
    Album,
    AuditLog,
    Generation,
    Song,
    User,
    Version,
)

_ADMIN_USER = "admin"


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
    mp3_path: str | None = None,
    song_deleted_at: datetime | None = None,
) -> None:
    session.add(
        Song(
            id=song_id, title=song_id, album_id=album_id, track_number=1, slug=song_id,
            deleted_at=song_deleted_at,
        ),
    )
    session.add(Version(id=f"v-{song_id}", song_id=song_id, version_number=1, lyrics="l"))
    session.add(Generation(
        id=f"g-{song_id}", song_id=song_id, version_id=f"v-{song_id}",
        generation_number=1,
        mp3_path=f"{_ADMIN_USER}/{song_id}.mp3" if mp3_path is None else mp3_path, seed=1,
        is_picked=is_picked, is_archived=is_archived,
    ))


def _seed_pick_scenarios(session) -> None:
    session.add(User(
        username=_ADMIN_USER, role="admin",
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


@pytest.fixture
def picks_client(tmp_path: Path):
    client, factory = make_test_app(tmp_path, seed_db=_seed_pick_scenarios)
    seed_session(client, _ADMIN_USER)
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

    queries, handle = _count_queries(engine, "from songs", "join generations", "is_picked")
    try:
        resp = client.get("/api/albums")
    finally:
        event.remove(engine, "before_cursor_execute", handle)

    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 3
    assert len(queries) == 1, (
        f"expected one aggregate pick-count query for all albums, got {len(queries)}: {queries}"
    )


def test_list_albums_computes_has_playable_take_in_one_aggregate_query(picks_client) -> None:
    """defect:#1430 -- the per-album answer comes from one query per page."""
    client, factory = picks_client
    with factory() as probe_session:
        engine = probe_session.get_bind()

    queries, handle = _count_queries(engine, "distinct songs.album_id", "join generations")
    try:
        resp = client.get("/api/albums")
    finally:
        event.remove(engine, "before_cursor_execute", handle)

    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 3
    assert len(queries) == 1, (
        f"expected one aggregate playable-take query for all albums, got {len(queries)}: {queries}"
    )


def test_list_albums_computes_song_count_in_one_aggregate_query(picks_client) -> None:
    """#340: song_count must come from one aggregate query, never from
    joinedload(Album.songs) + len() -- that reintroduces the album-list
    equivalent of the per-song generation-count N+1."""
    client, factory = picks_client
    with factory() as probe_session:
        engine = probe_session.get_bind()

    all_queries, all_handle = _count_queries(engine)
    queries, handle = _count_queries(engine, "from songs", "count(songs.id)")
    try:
        resp = client.get("/api/albums")
    finally:
        event.remove(engine, "before_cursor_execute", all_handle)
        event.remove(engine, "before_cursor_execute", handle)

    all_queries = queries_without_session_auth(all_queries)
    assert resp.status_code == 200
    by_id = {a["id"]: a for a in resp.json()["items"]}
    assert by_id["no-songs"]["song_count"] == 0
    assert by_id["one-pick"]["song_count"] == 2
    assert by_id["many-picks"]["song_count"] == 4
    assert len(queries) == 1, (
        f"expected one aggregate song-count query for all albums, got {len(queries)}: {queries}"
    )
    # Fixed budget for GET /api/albums against this fixture: one count(*)
    # for the page total, one SELECT for the page of albums, one aggregate
    # picked-count query, one aggregate song-count query, one aggregate
    # playable-take query -- never a query per album. Pinned alongside the
    # aggregate-only assertion above so a
    # regression on an unrelated relationship shows up here even when the
    # two counted aggregates stay at one query each.
    assert len(all_queries) == 5, (
        f"expected exactly 5 queries for GET /api/albums against this fixture "
        f"(count + page + picked-count + song-count + playable-take aggregates), "
        f"got {len(all_queries)}: {all_queries}"
    )


def test_list_albums_song_count_excludes_soft_deleted_song(tmp_path: Path) -> None:
    """#340 F1: count_songs_by_album() must honor the global soft-delete
    filter (db/soft_delete.py) the same way the old joinedload(Album.songs)
    + len() path did -- a soft-deleted song was never visible through that
    relationship either, so the aggregate must not silently count it back in."""
    def _seed(session) -> None:
        session.add(User(
            username=_ADMIN_USER, role="admin",
        ))
        session.add(Album(id="alb", title="Album", artist="A"))
        session.add(Song(id="live", title="Live", album_id="alb", track_number=1, slug="live"))
        session.add(Song(
            id="gone", title="Gone", album_id="alb", track_number=2, slug="gone",
            deleted_at=datetime.now(timezone.utc),
        ))

    client, _ = make_test_app(tmp_path, seed_db=_seed)
    seed_session(client, _ADMIN_USER)
    resp = client.get("/api/albums")
    assert resp.status_code == 200
    by_id = {a["id"]: a for a in resp.json()["items"]}
    assert by_id["alb"]["song_count"] == 1


def _seed_playable_take_scenarios(session) -> None:
    session.add(User(
        username=_ADMIN_USER, role="admin",
    ))
    for album_id in (
        "no-songs", "songless-song", "only-archived", "only-empty-mp3", "empty-and-archived",
        "one-playable-among-archived", "only-soft-deleted",
    ):
        session.add(Album(id=album_id, title=album_id, artist="A"))
    session.add(Song(
        id="bare", title="Bare", album_id="songless-song", track_number=1, slug="bare",
    ))
    _add_song_with_generation(
        session, song_id="arch", album_id="only-archived", is_archived=True,
    )
    _add_song_with_generation(session, song_id="blank", album_id="only-empty-mp3", mp3_path="")
    _add_song_with_generation(
        session, song_id="blank-arch", album_id="empty-and-archived",
        mp3_path="", is_archived=True,
    )
    _add_song_with_generation(
        session, song_id="old", album_id="one-playable-among-archived", is_archived=True,
    )
    _add_song_with_generation(session, song_id="good", album_id="one-playable-among-archived")
    _add_song_with_generation(
        session, song_id="gone", album_id="only-soft-deleted",
        song_deleted_at=datetime.now(timezone.utc),
    )


_PLAYABLE_TAKE_EXPECTATIONS = {
    "no-songs": False,
    "songless-song": False,
    "only-archived": False,
    "only-empty-mp3": False,
    "empty-and-archived": False,
    "one-playable-among-archived": True,
    "only-soft-deleted": False,
}


@pytest.fixture
def playable_take_client(tmp_path: Path):
    client, _ = make_test_app(tmp_path, seed_db=_seed_playable_take_scenarios)
    seed_session(client, _ADMIN_USER)
    return client


def test_list_albums_reports_has_playable_take_per_album_1354_rule_11(
    playable_take_client,
) -> None:
    resp = playable_take_client.get("/api/albums")
    assert resp.status_code == 200
    reported = {a["id"]: a["has_playable_take"] for a in resp.json()["items"]}
    assert reported == _PLAYABLE_TAKE_EXPECTATIONS


@pytest.mark.parametrize(("album_id", "expected"), _PLAYABLE_TAKE_EXPECTATIONS.items())
def test_get_album_agrees_with_list_on_has_playable_take_1354_rule_11(
    playable_take_client, album_id: str, expected: bool,
) -> None:
    resp = playable_take_client.get(f"/api/albums/{album_id}")
    assert resp.status_code == 200
    assert resp.json()["has_playable_take"] is expected


def test_created_album_has_no_playable_take_1354_rule_11(playable_take_client) -> None:
    client = playable_take_client
    resp = client.post("/api/albums", json={"title": "Fresh"})
    assert resp.status_code == 200
    assert resp.json()["has_playable_take"] is False


def _seed_metadata_scenarios(session) -> None:
    session.add(User(
        username=_ADMIN_USER, role="admin",
    ))
    session.add(Album(
        id="meta-album", title="Meta Album", artist="A",
        subtitle="Old Subtitle", year="1999",
    ))


@pytest.fixture
def metadata_client(tmp_path: Path):
    client, factory = make_test_app(tmp_path, seed_db=_seed_metadata_scenarios)
    seed_session(client, _ADMIN_USER)
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
            id="u-owner", username="owner",
            role="user",
        ))
        session.add(User(
            id="u-intruder", username="intruder",
            role="user",
        ))
        session.flush()
        session.add(Album(
            id="theirs", title="Theirs", artist="A", created_by="u-owner",
            subtitle="Untouched",
        ))

    client, factory = make_test_app(tmp_path, seed_db=_seed)
    seed_session(client, "intruder")
    resp = client.put("/api/albums/theirs", json={"subtitle": "Hijacked"})
    assert resp.status_code == 404
    with factory() as session:
        assert session.query(Album).filter_by(id="theirs").first().subtitle == "Untouched"


def _seed_archive_scenarios(session) -> None:
    session.add(User(
        username=_ADMIN_USER, role="admin",
    ))
    session.add(Album(id="live-one", title="Live One", artist="A"))
    session.add(Album(id="live-two", title="Live Two", artist="A"))
    session.add(Album(id="already-archived", title="Already Archived", artist="A"))


@pytest.fixture
def archive_client(tmp_path: Path):
    client, factory = make_test_app(tmp_path, seed_db=_seed_archive_scenarios)
    seed_session(client, _ADMIN_USER)
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


def test_archived_filter_song_count_counts_songs_of_archived_album(tmp_path: Path) -> None:
    """#340 F1: song_count for an archived album, reached via ?archived=true,
    must still reflect its songs -- count_songs_by_album() is grouped by the
    album ids the caller passes in, not filtered by is_archived itself, so
    it must not accidentally go blind on the archived branch."""
    def _seed(session) -> None:
        session.add(User(
            username=_ADMIN_USER, role="admin",
        ))
        session.add(Album(id="alb", title="Album", artist="A", is_archived=True))
        session.add(Song(id="s1", title="One", album_id="alb", track_number=1, slug="one"))
        session.add(Song(id="s2", title="Two", album_id="alb", track_number=2, slug="two"))

    client, _ = make_test_app(tmp_path, seed_db=_seed)
    seed_session(client, _ADMIN_USER)
    resp = client.get("/api/albums", params={"archived": "true"})
    assert resp.status_code == 200
    by_id = {a["id"]: a for a in resp.json()["items"]}
    assert by_id["alb"]["song_count"] == 2


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
            id="u-owner", username="owner",
            role="user",
        ))
        session.add(User(
            id="u-intruder", username="intruder",
            role="user",
        ))
        session.flush()
        session.add(Album(id="theirs", title="Theirs", artist="A", created_by="u-owner"))

    client, factory = make_test_app(tmp_path, seed_db=_seed)
    seed_session(client, "intruder")
    resp = client.post("/api/albums/theirs/archive")
    assert resp.status_code == 404
    with factory() as session:
        assert session.query(Album).filter_by(id="theirs").first().is_archived is False


def test_unarchive_other_users_album_is_404(tmp_path: Path) -> None:
    def _seed(session) -> None:
        session.add(User(
            id="u-owner", username="owner",
            role="user",
        ))
        session.add(User(
            id="u-intruder", username="intruder",
            role="user",
        ))
        session.flush()
        session.add(Album(
            id="theirs", title="Theirs", artist="A", created_by="u-owner", is_archived=True,
        ))

    client, factory = make_test_app(tmp_path, seed_db=_seed)
    seed_session(client, "intruder")
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


# ── Slug overflow (#271) ─────────────────────────────────────────────────


@pytest.fixture
def creation_client(tmp_path: Path):
    def _seed(session) -> None:
        session.add(User(
            username=_ADMIN_USER, role="admin",
        ))

    client, factory = make_test_app(tmp_path, seed_db=_seed)
    seed_session(client, _ADMIN_USER)
    return client, factory


def test_create_album_with_200_char_title_succeeds(creation_client) -> None:
    client, _ = creation_client
    title = "A" * 200
    resp = client.post("/api/albums", json={"title": title})
    assert resp.status_code == 200
    album_id = resp.json()["id"]
    assert len(album_id) <= ALBUM_SLUG_MAX_LENGTH


def test_create_album_with_cjk_title_succeeds(creation_client) -> None:
    client, _ = creation_client
    title = "音" * 200
    resp = client.post("/api/albums", json={"title": title})
    assert resp.status_code == 200
    album_id = resp.json()["id"]
    assert len(album_id) <= ALBUM_SLUG_MAX_LENGTH


def test_create_album_slug_collision_at_budget_edge_appends_suffix(
    creation_client,
) -> None:
    """A 200-char title that truncates to a base slug, and a second title
    sharing that truncated prefix, collide on the same base slug — the
    second create must still fit within ALBUM_SLUG_MAX_LENGTH once the "-2"
    counter suffix is appended.

    The truncation point is read back from the first response rather than
    assumed, so the test tracks the real budget instead of a duplicated
    constant."""
    client, _ = creation_client
    title_a = "x" * 200

    first = client.post("/api/albums", json={"title": title_a})
    assert first.status_code == 200
    first_id = first.json()["id"]
    assert len(first_id) <= ALBUM_SLUG_MAX_LENGTH
    assert 0 < len(first_id) < len(title_a), "title must actually get truncated"

    title_b = first_id + "B" + "z" * (len(title_a) - len(first_id) - 1)
    second = client.post("/api/albums", json={"title": title_b})
    assert second.status_code == 200
    second_id = second.json()["id"]
    assert second_id == f"{first_id}-2"
    assert len(second_id) <= ALBUM_SLUG_MAX_LENGTH
