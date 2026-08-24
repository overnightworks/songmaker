"""Regression coverage for issue #153 — library search finding real titles.

Pins the exact shape of the reported bug: an album and a song that share the
same title must both surface from GET /api/library/search, including when
the title contains non-ASCII (umlaut) characters and the query differs in
case from the stored title.

Also pins issue #236 — a QA exploration reported that searching an admin
account for "Thomas"/"für"/"42" found nothing for the album "42 — Für
Thomas", while other titles matched. Root cause: that album belongs to a
different (non-admin) user, and search is intentionally scoped to the
searcher's own titles even for admins (commit 7a05e1e, "keep search
personal") — album/song *browse* lists are the only surfaces where admins
see everyone's content. There is no tokenization, em-dash, or number-token
defect in `like_contains_pattern`/`title_matches`: the tests below prove
each of those three query shapes matches correctly for the title's owner,
and stays empty for a same-titled admin who does not own it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from conftest import TEST_SECRET, make_fake_redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.auth import ROLE_ADMIN
from songmaker_cli.constants import LIBRARY_ITEM_ALBUM, LIBRARY_ITEM_SONG
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Song, User, Version
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

OWNER_ID = "owner"
ADMIN_ID = "admin"


def _client_with_title(
    tmp_path: Path,
    *,
    album_title: str,
    song_title: str,
    searcher: AuthenticatedUser | None = None,
) -> TestClient:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id=OWNER_ID, username="owner", password_hash="unused", role="user",
        ))
        session.add(User(
            id=ADMIN_ID, username="admin", password_hash="unused", role=ROLE_ADMIN,
        ))
        session.flush()
        session.add(Album(
            id="album-1", title=album_title, artist="Artist",
            created_by=OWNER_ID, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ))
        session.add(Song(
            id="song-1", title=song_title, album_id="album-1", track_number=1,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ))
        session.add(Version(
            song_id="song-1", version_number=1, lyrics="lyrics", prompt="prompt",
        ))
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = lambda: searcher or AuthenticatedUser(
        id=OWNER_ID, username="owner", role="user", is_active=True,
    )
    app.include_router(router)
    return TestClient(app)


def _hit_types(items: list[dict]) -> set[str]:
    return {item["type"] for item in items}


def test_search_finds_album_and_song_sharing_the_exact_title(tmp_path: Path) -> None:
    client = _client_with_title(tmp_path, album_title="Sommerlicht", song_title="Sommerlicht")

    resp = client.get("/api/library/search", params={"q": "Sommerlicht"})

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert _hit_types(items) == {LIBRARY_ITEM_ALBUM, LIBRARY_ITEM_SONG}


@pytest.mark.parametrize("query", ["Nächte", "nächte"])
def test_search_matches_umlaut_title(tmp_path: Path, query: str) -> None:
    client = _client_with_title(tmp_path, album_title="Nächte", song_title="Nächte")

    resp = client.get("/api/library/search", params={"q": query})

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert _hit_types(items) == {LIBRARY_ITEM_ALBUM, LIBRARY_ITEM_SONG}


def test_search_matches_lowercase_query_against_capitalized_title(tmp_path: Path) -> None:
    client = _client_with_title(tmp_path, album_title="Sommerlicht", song_title="Sommerlicht")

    resp = client.get("/api/library/search", params={"q": "sommerlicht"})

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert _hit_types(items) == {LIBRARY_ITEM_ALBUM, LIBRARY_ITEM_SONG}


ALBUM_236 = "42 — Für Thomas"
SONG_236 = "42 (Thomas, du Legende)"


@pytest.mark.parametrize(
    "query",
    ["Thomas", "thomas", "Für", "für", "42"],
    ids=["album-title-word", "album-title-word-lower", "word-after-em-dash",
         "word-after-em-dash-lower", "number-token"],
)
def test_search_finds_owners_em_dash_and_number_title(tmp_path: Path, query: str) -> None:
    """Issue #236 categories, searched by the title's actual owner.

    Proves like_contains_pattern/title_matches has no defect for a leading
    number token or a word directly after an em dash — the two shapes named
    in the bug report as suspects.
    """
    client = _client_with_title(tmp_path, album_title=ALBUM_236, song_title=SONG_236)

    resp = client.get("/api/library/search", params={"q": query})

    assert resp.status_code == 200
    types = _hit_types(resp.json()["items"])
    assert LIBRARY_ITEM_ALBUM in types, f"query {query!r} did not find the album"


@pytest.mark.parametrize("query", ["Thomas", "Für", "42"])
def test_admin_search_stays_empty_for_another_users_title(tmp_path: Path, query: str) -> None:
    """Issue #236 root cause, pinned: this is ownership scoping, not a query bug.

    The reported "0 Treffer" came from an admin account searching for a
    title owned by a different user. Search is intentionally scoped to the
    searcher's own titles even for admins (commit 7a05e1e) — admins only see
    other users' content in the browse/list endpoints, never in search.
    """
    admin = AuthenticatedUser(id=ADMIN_ID, username="admin", role=ROLE_ADMIN, is_active=True)
    client = _client_with_title(
        tmp_path, album_title=ALBUM_236, song_title=SONG_236, searcher=admin,
    )

    resp = client.get("/api/library/search", params={"q": query})

    assert resp.status_code == 200
    assert resp.json()["items"] == []
