"""Library search — every sort pages through albums and songs in one stable order."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.constants import (
    LIBRARY_ITEM_ALBUM,
    LIBRARY_ITEM_SONG,
    LIBRARY_SORT_NEWEST,
    LIBRARY_SORT_OLDEST,
    LIBRARY_SORT_TITLE,
)
from songmaker_cli.db.models import Album, Song, User, Version
from songmaker_cli.library_cursor import decode_library_cursor

OWNER = "order-owner"
QUERY = "mix"


def _created(offset_seconds: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)


def _album(session, album_id: str, title: str, at: int) -> None:
    session.add(Album(
        id=album_id, title=title, artist="Artist", created_by=OWNER, created_at=_created(at),
    ))


def _song(session, song_id: str, title: str, album_id: str, at: int) -> None:
    session.add(Song(
        id=song_id, title=title, album_id=album_id, track_number=1,
        created_at=_created(at), updated_at=_created(at), slug=song_id,
    ))
    session.add(Version(song_id=song_id, version_number=1, lyrics="lyrics", prompt="prompt"))


def _seed_equal_titles_and_times(session) -> None:
    _album(session, "a1", "Tie mix", 10)
    _album(session, "a2", "Tie mix", 10)
    _song(session, "s1", "Tie mix", "a1", 10)
    _song(session, "s2", "Tie mix", "a2", 10)


def _seed_interleaved_titles(session) -> None:
    _album(session, "zebra", "Zebra mix", 10)
    _album(session, "umlaut", "Äpfel mix", 20)
    _album(session, "plain", "Bravo mix", 30)
    _song(session, "apfel", "apfel mix", "plain", 25)
    _song(session, "mango", "Mango mix", "zebra", 5)


def _seed_differing_and_tied_times(session) -> None:
    _album(session, "a-early", "Early mix", 1)
    _album(session, "a-tie-1", "Tie one mix", 3)
    _album(session, "a-tie-2", "Tie two mix", 3)
    _song(session, "s-mid", "Mid mix", "a-early", 2)
    _song(session, "s-tie", "Tie song mix", "a-early", 3)


def _hit_ids(items: list[dict]) -> list[str]:
    return [
        item["album"]["id"] if item["type"] == LIBRARY_ITEM_ALBUM else item["song"]["id"]
        for item in items
    ]


@pytest.fixture
def order_env(tmp_path: Path, pg_factory) -> Callable[[Callable], tuple[TestClient, object]]:
    def build(seed: Callable) -> tuple[TestClient, object]:
        with pg_factory() as session:
            session.add(User(id=OWNER, username="order-owner", role="user"))
            session.flush()
            seed(session)
            session.commit()
        ctx = make_router_ctx(tmp_path, db=pg_factory)
        app = make_router_app(
            ctx, user=make_authenticated_user(OWNER, role="user", username="test-order-owner"),
        )
        return web_client(app), ctx

    return build


def _walk(client: TestClient, sort: str, limit: int) -> list[str]:
    ids: list[str] = []
    cursor = None
    while True:
        params: dict[str, str | int] = {"q": QUERY, "sort": sort, "limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get("/api/library/search", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        ids.extend(_hit_ids(body["items"]))
        if not body["has_more"]:
            return ids
        cursor = body["next_cursor"]


ORDERS = [
    pytest.param(
        _seed_equal_titles_and_times, LIBRARY_SORT_TITLE, ["a1", "a2", "s1", "s2"],
        id="title-ties-album-first-then-id-ascending",
    ),
    pytest.param(
        _seed_equal_titles_and_times, LIBRARY_SORT_OLDEST, ["a1", "a2", "s1", "s2"],
        id="oldest-ties-album-first-then-id-ascending",
    ),
    pytest.param(
        _seed_equal_titles_and_times, LIBRARY_SORT_NEWEST, ["a2", "a1", "s2", "s1"],
        id="newest-ties-album-first-then-id-descending",
    ),
    pytest.param(
        _seed_interleaved_titles, LIBRARY_SORT_TITLE,
        ["apfel", "plain", "mango", "zebra", "umlaut"],
        id="title-orders-by-lowercased-title",
    ),
    pytest.param(
        _seed_interleaved_titles, LIBRARY_SORT_OLDEST,
        ["mango", "zebra", "umlaut", "apfel", "plain"],
        id="oldest-interleaves-albums-and-songs",
    ),
    pytest.param(
        _seed_interleaved_titles, LIBRARY_SORT_NEWEST,
        ["plain", "apfel", "umlaut", "zebra", "mango"],
        id="newest-interleaves-albums-and-songs",
    ),
    pytest.param(
        _seed_differing_and_tied_times, LIBRARY_SORT_OLDEST,
        ["a-early", "s-mid", "a-tie-1", "a-tie-2", "s-tie"],
        id="oldest-merges-differing-and-tied-times",
    ),
    pytest.param(
        _seed_differing_and_tied_times, LIBRARY_SORT_NEWEST,
        ["a-tie-2", "a-tie-1", "s-tie", "s-mid", "a-early"],
        id="newest-merges-differing-and-tied-times",
    ),
]


@pytest.mark.parametrize("limit", [1, 2, 5])
@pytest.mark.parametrize(("seed", "sort", "expected"), ORDERS)
def test_walking_every_page_yields_each_hit_once_in_the_documented_order(
    order_env, seed: Callable, sort: str, expected: list[str], limit: int,
) -> None:
    client, _ctx = order_env(seed)

    assert _walk(client, sort, limit) == expected


@pytest.mark.parametrize(
    ("sort", "expected_key"),
    [
        (LIBRARY_SORT_TITLE, "bravo mix"),
        (LIBRARY_SORT_OLDEST, _created(20).isoformat()),
        (LIBRARY_SORT_NEWEST, _created(30).isoformat()),
    ],
)
def test_the_cursor_carries_the_last_hits_sort_key(
    order_env, sort: str, expected_key: str,
) -> None:
    client, ctx = order_env(_seed_interleaved_titles)
    limit = {LIBRARY_SORT_TITLE: 2, LIBRARY_SORT_OLDEST: 3, LIBRARY_SORT_NEWEST: 1}[sort]

    body = client.get(
        "/api/library/search", params={"q": QUERY, "sort": sort, "limit": limit},
    ).json()
    cursor = decode_library_cursor(body["next_cursor"], ctx.signing_key, q=QUERY, sort=sort)

    assert cursor.sort_value == expected_key
    assert cursor.item_type in {LIBRARY_ITEM_ALBUM, LIBRARY_ITEM_SONG}
