"""Song list API tests — generation_count on SongSummaryResponse (#340).

The song list previously touched each song's (unloaded) generations
relationship just to count it, costing one lazy-load query per row.
generation_count is now computed server-side in one aggregate query.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import login_and_csrf, make_test_app
from sqlalchemy import event

from songmaker_cli.auth import hash_password
from songmaker_cli.db.models import Album, Generation, Song, User, Version

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
