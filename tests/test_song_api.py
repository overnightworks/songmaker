"""Song list/detail API tests — query-cost regressions (#340, #331 Finding 1).

The song list previously touched each song's (unloaded) generations
relationship just to count it, costing one lazy-load query per row.
generation_count is now computed server-side in one aggregate query.

GET /api/songs/{id} previously joinedload()ed three sibling/nested
collections (versions, generations, generations.scores) in one query,
producing a SQL cross join -- one row per (version, generation, score)
combination. This file also pins its query count after the selectinload()
fix (#331 Finding 1).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import login_and_csrf, make_test_app
from sqlalchemy import event

from songmaker_cli.auth import hash_password
from songmaker_cli.db.models import Album, Generation, Score, Song, User, Version
from songmaker_cli.db.queries.songs import list_songs

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


def _add_song_with_generations(
    session, *, song_id: str, album_id: str, track_number: int, generation_count: int,
    is_archived: bool = False,
) -> None:
    session.add(Song(
        id=song_id, title=song_id, album_id=album_id,
        track_number=track_number, slug=song_id,
    ))
    session.add(Version(id=f"v-{song_id}", song_id=song_id, version_number=1, lyrics="l"))
    for i in range(generation_count):
        session.add(Generation(
            id=f"g-{song_id}-{i}", song_id=song_id, version_id=f"v-{song_id}",
            generation_number=i + 1, mp3_path=f"{_ADMIN_USER}/{song_id}-{i}.mp3", seed=1,
            is_archived=is_archived,
        ))


def _seed_generation_count_scenarios(session) -> None:
    session.add(User(
        username=_ADMIN_USER, password_hash=hash_password(_ADMIN_PASSWORD), role="admin",
    ))
    session.add(Album(id="alb", title="Album", artist="A"))
    _add_song_with_generations(
        session, song_id="no-takes", album_id="alb", track_number=1, generation_count=0,
    )
    _add_song_with_generations(
        session, song_id="one-take", album_id="alb", track_number=2, generation_count=1,
    )
    _add_song_with_generations(
        session, song_id="many-takes", album_id="alb", track_number=3, generation_count=5,
    )
    _add_song_with_generations(
        session, song_id="archived-take", album_id="alb", track_number=4,
        generation_count=1, is_archived=True,
    )


@pytest.fixture()
def generation_count_client(tmp_path: Path):
    client, factory = make_test_app(tmp_path, seed_db=_seed_generation_count_scenarios)
    login_and_csrf(client, _ADMIN_USER, _ADMIN_PASSWORD)
    return client, factory


def test_list_songs_generation_count_zero_when_no_takes(generation_count_client) -> None:
    client, _ = generation_count_client
    resp = client.get("/api/songs")
    assert resp.status_code == 200
    by_id = {s["id"]: s for s in resp.json()["items"]}
    assert by_id["no-takes"]["generation_count"] == 0


def test_list_songs_generation_count_counts_one_take(generation_count_client) -> None:
    client, _ = generation_count_client
    resp = client.get("/api/songs")
    by_id = {s["id"]: s for s in resp.json()["items"]}
    assert by_id["one-take"]["generation_count"] == 1


def test_list_songs_generation_count_counts_n_takes(generation_count_client) -> None:
    client, _ = generation_count_client
    resp = client.get("/api/songs")
    by_id = {s["id"]: s for s in resp.json()["items"]}
    assert by_id["many-takes"]["generation_count"] == 5


def test_list_songs_generation_count_counts_archived_take(generation_count_client) -> None:
    """#340 F1: an archived generation must still count, matching the old
    len(song.generations) behaviour -- count_generations_by_song() carries
    no is_archived filter, unlike count_picked_songs_by_album()'s picked
    aggregate, which deliberately excludes archived picks."""
    client, _ = generation_count_client
    resp = client.get("/api/songs")
    by_id = {s["id"]: s for s in resp.json()["items"]}
    assert by_id["archived-take"]["generation_count"] == 1


def test_list_songs_computes_generation_count_in_one_aggregate_query(
    generation_count_client,
) -> None:
    client, factory = generation_count_client
    with factory() as probe_session:
        engine = probe_session.get_bind()

    all_queries, all_handle = _count_queries(engine)
    aggregate_queries, aggregate_handle = _count_queries(engine, "from generations", "group by")
    try:
        resp = client.get("/api/songs")
    finally:
        event.remove(engine, "before_cursor_execute", all_handle)
        event.remove(engine, "before_cursor_execute", aggregate_handle)

    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 4
    assert len(aggregate_queries) == 1, (
        f"expected one aggregate generation-count query for all songs, "
        f"got {len(aggregate_queries)}: {aggregate_queries}"
    )
    # Fixed budget for GET /api/songs against this fixture: one count(*) for
    # the page total, one SELECT for the page of songs (+versions +album via
    # joinedload, no extra round trip), one aggregate generations count --
    # never a query per song. A regression on an unrelated relationship
    # (e.g. an N+1 reintroduced on Song.versions) changes this number
    # without changing the aggregate-query assertion above, which is why
    # both are pinned.
    assert len(all_queries) == 3, (
        f"expected exactly 3 queries for GET /api/songs against this fixture "
        f"(count + page + aggregate generation-count), got {len(all_queries)}: {all_queries}"
    )


# ── GET /api/songs/{id} — selectinload() over the sibling collections ────
# (#331 Finding 1). A worked-through song with 12 versions, 25 generations,
# and 7 scores per generation used to joinedload() all three onto one query,
# producing the SQL cross join versions x generations x scores: 12 * 25 * 7
# = 2,100 rows, each repeating the full lyrics text and score JSON
# (including the whisper transcript). selectinload() replaces the cross
# join with one flat batched query per collection.

_DETAIL_VERSION_COUNT = 12
_DETAIL_GENERATION_COUNT = 25
_DETAIL_SCORES_PER_GENERATION = 7


def _seed_worked_through_song(session) -> None:
    session.add(User(
        username=_ADMIN_USER, password_hash=hash_password(_ADMIN_PASSWORD), role="admin",
    ))
    session.add(Album(id="alb", title="Album", artist="A"))
    session.add(Song(id="s1", title="s1", album_id="alb", track_number=1, slug="s1"))
    for i in range(_DETAIL_VERSION_COUNT):
        session.add(Version(
            id=f"v{i}", song_id="s1", version_number=i + 1, lyrics="lyrics " * 200,
        ))
    for i in range(_DETAIL_GENERATION_COUNT):
        gen_id = f"g{i}"
        session.add(Generation(
            id=gen_id, song_id="s1", version_id="v0",
            generation_number=i + 1, mp3_path=f"{_ADMIN_USER}/{gen_id}.mp3", seed=1,
        ))
        for j in range(_DETAIL_SCORES_PER_GENERATION):
            session.add(Score(
                id=f"{gen_id}-sc{j}", generation_id=gen_id, scorer=f"scorer{j}",
                value={f"whisper_text_{j}": "transcript " * 100},
            ))


@pytest.fixture()
def worked_through_song_client(tmp_path: Path):
    client, factory = make_test_app(tmp_path, seed_db=_seed_worked_through_song)
    login_and_csrf(client, _ADMIN_USER, _ADMIN_PASSWORD)
    return client, factory


def test_get_song_returns_all_versions_generations_and_scores(
    worked_through_song_client,
) -> None:
    client, _ = worked_through_song_client
    resp = client.get("/api/songs/s1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version_count"] == _DETAIL_VERSION_COUNT
    assert body["generation_count"] == _DETAIL_GENERATION_COUNT
    assert len(body["generations"]) == _DETAIL_GENERATION_COUNT
    assert len(body["generations"][0]["scores"]) == _DETAIL_SCORES_PER_GENERATION


def test_get_song_issues_one_flat_query_per_collection_not_a_cross_join(
    worked_through_song_client,
) -> None:
    """Pins the exact query count for GET /api/songs/{id}: one for the song
    row (+album via joinedload), one selectinload() batch each for versions,
    generations, and generations.scores -- never a single query whose row
    count multiplies across all three collections, and never a query per
    row (which would also prove the #340 weak-identity-map pitfall doesn't
    apply here: gen.version is read, but it's the forward relation loaded
    directly per-row, not a Generation.song back-populate off a parent list
    that has gone out of scope, and nothing on this path reads that
    direction at all)."""
    client, factory = worked_through_song_client
    with factory() as probe_session:
        engine = probe_session.get_bind()

    all_queries, all_handle = _count_queries(engine)
    try:
        resp = client.get("/api/songs/s1")
    finally:
        event.remove(engine, "before_cursor_execute", all_handle)

    assert resp.status_code == 200
    assert len(all_queries) == 4, (
        f"expected exactly 4 queries for GET /api/songs/{{id}} against this "
        f"fixture (song+album, versions, generations, scores), "
        f"got {len(all_queries)}: {all_queries}"
    )


def test_list_songs_with_full_details_loads_one_flat_query_per_collection_not_a_cross_join(
    worked_through_song_client,
) -> None:
    """The explicit detailed list path loads each collection flatly."""
    _, factory = worked_through_song_client
    with factory() as probe_session:
        engine = probe_session.get_bind()

    all_queries, all_handle = _count_queries(engine)
    try:
        with factory() as session:
            songs = list_songs(session, album_id="alb", light=False)
            assert len(songs) == 1
            assert len(songs[0].versions) == _DETAIL_VERSION_COUNT
            assert len(songs[0].generations) == _DETAIL_GENERATION_COUNT
            assert len(songs[0].generations[0].scores) == _DETAIL_SCORES_PER_GENERATION
    finally:
        event.remove(engine, "before_cursor_execute", all_handle)

    assert len(all_queries) == 4, (
        f"expected exactly 4 queries for detailed list_songs(light=False) against this "
        f"fixture (songs+album, versions, generations, scores), "
        f"got {len(all_queries)}: {all_queries}"
    )
