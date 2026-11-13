"""The library routes refuse with a catalog key, and a foreign resource reads as a missing one."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from support.mcp_tool_table import ALICE, BOB
from support.mcp_world import McpWorld
from support.web_app import (
    make_authenticated_user,
    make_router_app,
    make_router_ctx,
    refusal_body,
    web_client,
)

from songmaker_cli.db.models import (
    Album,
    Generation,
    Playlist,
    PlaylistEntry,
    Song,
    User,
    Version,
)
from songmaker_cli.db.queries.songs import (
    EmptySongTitleError,
    OverlongSongTitleError,
    UnstorableSongTitleError,
)
from songmaker_cli.words import Key

OWNER_ID = "owner"
STRANGER_ID = "stranger"
MISSING_ID = "no-such-id"


@pytest.fixture
def library(tmp_path: Path, pg_factory) -> dict[str, TestClient]:
    """An owner's album, song, version, playlist and entry, and clients for both musicians."""
    with pg_factory() as session:
        for user_id in (OWNER_ID, STRANGER_ID):
            session.add(User(id=user_id, username=user_id, role="user"))
        session.flush()
        session.add(Album(id="album", title="Album", artist="Band", created_by=OWNER_ID))
        session.add(Album(id="stranger-album", title="S", artist="Band", created_by=STRANGER_ID))
        session.add(Song(id="song", title="Song", album_id="album", slug="song"))
        session.add(Version(id="version", song_id="song", version_number=1))
        session.add(Generation(
            id="take", song_id="song", version_id="version", mp3_path=f"{OWNER_ID}/take.mp3",
        ))
        session.add(Song(
            id="deleted-song", title="Gone", album_id="album", slug="gone",
            deleted_at=datetime.now(timezone.utc),
        ))
        session.add(Playlist(id="playlist", title="Mix", slug="mix", created_by=OWNER_ID))
        session.add(Playlist(
            id="stranger-playlist", title="Theirs", slug="theirs", created_by=STRANGER_ID,
        ))
        session.flush()
        session.add(
            PlaylistEntry(id="entry", playlist_id="playlist", generation_id="take", position=0),
        )
        session.commit()
    ctx = make_router_ctx(tmp_path, db=pg_factory)
    return {
        user_id: web_client(
            make_router_app(ctx, user=make_authenticated_user(user_id, username=user_id)),
        )
        for user_id in (OWNER_ID, STRANGER_ID)
    }


@pytest.mark.parametrize(
    ("method", "path", "foreign_id", "key"),
    [
        ("get", "/api/albums/{}", "album", "albumRefusal.notFound"),
        ("get", "/api/songs/{}", "song", "songRefusal.notFound"),
        ("get", "/api/playlists/{}", "playlist", "playlistRefusal.notFound"),
        ("delete", "/api/versions/{}", "version", "versionRefusal.notFound"),
        ("post", "/api/songs/{}/restore", "deleted-song", "songRefusal.notFound"),
    ],
)
def test_a_foreign_resource_answers_the_body_of_a_missing_one(
    library: dict[str, TestClient], method: str, path: str, foreign_id: str, key: Key,
) -> None:
    stranger = library[STRANGER_ID]

    foreign = getattr(stranger, method)(path.format(foreign_id))
    missing = getattr(stranger, method)(path.format(MISSING_ID))

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == refusal_body(key)


@pytest.mark.parametrize("verb", ["delete", "patch"])
def test_an_entry_of_another_playlist_answers_the_body_of_a_missing_entry(
    library: dict[str, TestClient], verb: str,
) -> None:
    stranger = library[STRANGER_ID]
    body = {"json": {"new_position": 0}} if verb == "patch" else {}
    suffix = "/position" if verb == "patch" else ""

    entries = "/api/playlists/stranger-playlist/entries"

    foreign = getattr(stranger, verb)(f"{entries}/entry{suffix}", **body)
    missing = getattr(stranger, verb)(f"{entries}/{MISSING_ID}{suffix}", **body)

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == refusal_body("playlistRefusal.entryNotFound")


def test_a_blank_album_title_is_refused_on_create_and_on_rename(
    library: dict[str, TestClient],
) -> None:
    owner = library[OWNER_ID]

    created = owner.post("/api/albums", json={"title": "  ", "artist": "Band"})
    renamed = owner.put("/api/albums/album", json={"title": "  "})

    assert (created.status_code, renamed.status_code) == (422, 422)
    assert created.json() == renamed.json() == refusal_body("albumRefusal.titleRequired")


@pytest.mark.parametrize(
    ("raised", "key"),
    [
        (EmptySongTitleError, "songRefusal.titleRequired"),
        (OverlongSongTitleError, "songRefusal.titleTooLong"),
    ],
)
def test_a_song_title_that_cannot_be_stored_is_refused_with_its_reason(
    library: dict[str, TestClient],
    monkeypatch: pytest.MonkeyPatch,
    raised: type[UnstorableSongTitleError],
    key: Key,
) -> None:
    def unstorable(title: str) -> str:
        raise raised

    monkeypatch.setattr("songmaker_cli.song_api.stored_song_title", unstorable)

    response = library[OWNER_ID].put("/api/songs/song/title", json={"title": "Any"})

    assert response.status_code == 422
    assert response.json() == refusal_body(key)


def test_a_colliding_album_id_is_refused_with_the_title_as_a_gap(
    library: dict[str, TestClient], monkeypatch: pytest.MonkeyPatch,
) -> None:
    def collide(*args: object, **kwargs: object) -> None:
        raise IntegrityError("insert", {}, Exception("duplicate key"))

    monkeypatch.setattr("songmaker_cli.album_api.create_album", collide)

    response = library[OWNER_ID].post("/api/albums", json={"title": "Same", "artist": "Band"})

    assert response.status_code == 409
    assert response.json() == refusal_body("albumRefusal.idConflict", title="Same")


def test_restoring_a_song_whose_album_is_deleted_names_the_song(
    library: dict[str, TestClient],
) -> None:
    owner = library[OWNER_ID]
    owner.delete("/api/albums/album")

    response = owner.post("/api/songs/deleted-song/restore")

    assert response.status_code == 404
    assert response.json() == refusal_body("songRefusal.restoreAlbumDeleted", id="deleted-song")


def test_a_song_that_vanishes_during_a_restore_reads_like_a_missing_one(
    library: dict[str, TestClient], monkeypatch: pytest.MonkeyPatch,
) -> None:
    def vanished(*args: object, **kwargs: object) -> None:
        raise ValueError("Song not found: deleted-song")

    monkeypatch.setattr("songmaker_cli.song_api.restore_song", vanished)

    response = library[OWNER_ID].post("/api/songs/deleted-song/restore")

    assert response.status_code == 404
    assert response.json() == refusal_body("songRefusal.notFound")


def test_a_move_to_a_foreign_album_and_a_blank_discard_carry_their_keys(
    library: dict[str, TestClient],
) -> None:
    owner = library[OWNER_ID]

    moved = owner.put("/api/songs/song/album", json={"album_id": "stranger-album"})
    discarded = owner.delete("/api/albums/album/cover-suggestions")

    assert (moved.status_code, discarded.status_code) == (404, 422)
    assert moved.json() == refusal_body("albumRefusal.notFound")
    assert discarded.json() == refusal_body("coverSuggestionRefusal.nothingNamed")


def test_a_song_without_a_playable_take_is_refused_by_the_listen_and_the_playlist_routes(
    library: dict[str, TestClient],
) -> None:
    owner = library[OWNER_ID]
    owner.post("/api/songs", json={"title": "Bare", "album_id": "album"})
    bare_id = owner.get("/api/songs", params={"q": "Bare"}).json()["items"][0]["id"]

    listened = owner.post(f"/api/songs/{bare_id}/listen")
    added = owner.post("/api/playlists/playlist/entries/song", json={"song_id": bare_id})

    assert (listened.status_code, added.status_code) == (422, 400)
    assert listened.json() == refusal_body("songRefusal.notPlayable")
    assert added.json() == refusal_body("playlistRefusal.songNotPlayable")


def test_a_search_without_a_query_is_refused_with_its_key(
    library: dict[str, TestClient],
) -> None:
    response = library[OWNER_ID].get("/api/songs", params={"q": " "})

    assert response.status_code == 422
    assert response.json() == refusal_body("libraryRefusal.queryRequired")


def test_a_persons_own_agent_reads_a_foreign_song_like_a_missing_one(
    household: McpWorld,
) -> None:
    foreign = household.call("get_song", {"song_id": f"song-{BOB}"})
    missing = household.call("get_song", {"song_id": f"song-{ALICE}-missing"})

    assert foreign.is_error and missing.is_error
    assert foreign.json() == missing.json() == refusal_body("songRefusal.notFound")


def test_an_unknown_api_path_answers_not_found_without_a_message(
    library: dict[str, TestClient],
) -> None:
    response = library[OWNER_ID].get("/api/no-such-route")

    assert response.status_code == 404
    assert "message" not in response.json()
