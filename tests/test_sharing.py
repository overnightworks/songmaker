"""Tests for album sharing feature."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import TEST_SECRET, login_and_csrf, make_fake_redis, make_test_app
from fastapi.testclient import TestClient
from sqlalchemy import event

from songmaker_cli.app_context import AppContext
from songmaker_cli.auth import TrustedProxies, hash_password, sign_session_id
from songmaker_cli.constants import PLAYLIST_COVER_DIRNAME
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Generation, Playlist, PlaylistEntry, Song, User, Version

# The four share endpoints require PUBLIC_BASE_URL (#339); conftest.py sets
# the test-wide default ("Required env vars for Settings construction at
# module-import time"). Tests that pin the PUBLIC_BASE_URL contract itself
# override it via monkeypatch + get_settings.cache_clear().

_PROXY_NETWORK = "172.16.0.0/12"
_TRUSTED_PEER = "172.18.0.1"


def _seed_sharing_data(session) -> None:
    admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
    session.add(admin)
    session.add(Album(id="test_album", title="Test Album", artist="Test Artist"))
    session.add(
        Song(id="s1", title="Song One", album_id="test_album", track_number=1, slug="song-one"),
    )
    session.add(Version(id="v1", song_id="s1", version_number=1, lyrics="Hello"))
    session.add(Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="admin_user/g1.mp3", seed=42, is_picked=True,
    ))


def _make_sharing_app(tmp_path: Path) -> tuple[TestClient, Path]:
    client, _ = make_test_app(tmp_path, seed_db=_seed_sharing_data)
    audio_dir = tmp_path / "audio"
    user_dir = audio_dir / "admin_user"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "g1.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)
    return client, audio_dir


@pytest.fixture
def sharing_app(tmp_path: Path) -> TestClient:
    client, _ = _make_sharing_app(tmp_path)
    login_and_csrf(client, "admin", "admin12345")
    return client


# ── Share / Unshare endpoints ──────────────────────────────────────


def test_share_album(sharing_app: TestClient) -> None:
    resp = sharing_app.post("/api/albums/test_album/share")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["share_slug"]
    assert "/share/" in data["share_url"]
    assert data["songs_without_playable_take"] == []


def _seed_mixed_playability_album(session) -> None:
    admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
    session.add(admin)
    session.add(Album(id="test_album", title="Test Album", artist="Test Artist"))
    session.add(
        Song(
            id="s_playable", title="Has A Take", album_id="test_album", track_number=1,
            slug="has-a-take",
        ),
    )
    session.add(Generation(
        id="g_playable", song_id="s_playable", generation_number=1,
        mp3_path="admin_user/g_playable.mp3", seed=1, is_picked=True,
    ))
    session.add(Song(
        id="s_no_gen", title="No Generation At All", album_id="test_album", track_number=2,
        slug="no-generation-at-all",
    ))
    session.add(Song(
        id="s_archived_only", title="Only Archived Take", album_id="test_album", track_number=3,
        slug="only-archived-take",
    ))
    session.add(Generation(
        id="g_archived", song_id="s_archived_only", generation_number=1,
        mp3_path="admin_user/g_archived.mp3", seed=1, is_archived=True,
    ))
    session.add(Song(
        id="s_unpicked_take", title="Unpicked But Playable", album_id="test_album", track_number=4,
        slug="unpicked-but-playable",
    ))
    session.add(Generation(
        id="g_unpicked", song_id="s_unpicked_take", generation_number=1,
        mp3_path="admin_user/g_unpicked.mp3", seed=1, is_picked=False,
    ))
    session.add(Song(
        id="s_empty_mp3", title="Picked Take With Empty File",
        album_id="test_album", track_number=5, slug="picked-take-with-empty-file",
    ))
    session.add(Generation(
        id="g_empty_mp3", song_id="s_empty_mp3", generation_number=1,
        mp3_path="", seed=1, is_picked=True,
    ))


def test_share_album_response_lists_songs_without_playable_take(tmp_path: Path) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_mixed_playability_album)
    login_and_csrf(client, "admin", "admin12345")

    resp = client.post("/api/albums/test_album/share")

    assert resp.status_code == 200
    missing = resp.json()["songs_without_playable_take"]
    assert {(item["id"], item["title"]) for item in missing} == {
        ("s_no_gen", "No Generation At All"),
        ("s_archived_only", "Only Archived Take"),
        ("s_empty_mp3", "Picked Take With Empty File"),
    }


def test_share_warning_agrees_with_what_the_share_page_actually_plays(tmp_path: Path) -> None:
    """The owner-facing warning list and the public share page must use the
    same playability rule -- a song can't vanish from one without showing up
    in the other (#147)."""
    client, _ = make_test_app(tmp_path, seed_db=_seed_mixed_playability_album)
    login_and_csrf(client, "admin", "admin12345")

    share_resp = client.post("/api/albums/test_album/share")
    slug = share_resp.json()["share_slug"]
    warned_ids = {item["id"] for item in share_resp.json()["songs_without_playable_take"]}

    unauthed = TestClient(client.app, cookies={})
    shared_songs = unauthed.get(f"/shared/{slug}").json()["songs"]

    for song in shared_songs:
        has_audio = song["audio_url"] is not None
        assert has_audio == (song["id"] not in warned_ids)


def test_share_album_idempotent(sharing_app: TestClient) -> None:
    resp1 = sharing_app.post("/api/albums/test_album/share")
    slug1 = resp1.json()["share_slug"]
    resp2 = sharing_app.post("/api/albums/test_album/share")
    slug2 = resp2.json()["share_slug"]
    assert slug1 == slug2


def test_unshare_album(sharing_app: TestClient) -> None:
    sharing_app.post("/api/albums/test_album/share")
    resp = sharing_app.delete("/api/albums/test_album/share")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_share_nonexistent_album(sharing_app: TestClient) -> None:
    resp = sharing_app.post("/api/albums/nonexistent/share")
    assert resp.status_code == 404


def test_album_response_includes_sharing_fields(sharing_app: TestClient) -> None:
    resp = sharing_app.get("/api/albums/test_album")
    data = resp.json()
    assert data["is_shared"] is False
    assert data["share_slug"] is None

    sharing_app.post("/api/albums/test_album/share")
    resp = sharing_app.get("/api/albums/test_album")
    data = resp.json()
    assert data["is_shared"] is True
    assert data["share_slug"] is not None


# ── Shared view endpoints ──────────────────────────────────────────


def test_shared_album_view(sharing_app: TestClient) -> None:
    resp = sharing_app.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(sharing_app.app, cookies={})
    resp = unauthed.get(f"/shared/{slug}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Test Album"
    assert data["artist"] == "Test Artist"
    assert len(data["songs"]) == 1
    assert data["songs"][0]["title"] == "Song One"
    assert data["songs"][0]["audio_url"] is not None
    assert data["cover"] is None


def test_shared_album_not_found(sharing_app: TestClient) -> None:
    unauthed = TestClient(sharing_app.app, cookies={})
    resp = unauthed.get("/shared/nonexistent-slug")
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "scope",
    [
        pytest.param("shared-playlist", id="deleted-playlist"),
        pytest.param("shared-album", id="deleted-album"),
        pytest.param("unexpected", id="unexpected-scope"),
    ],
)
def test_shared_queue_manifest_rejects_resources_that_no_longer_exist(scope: str) -> None:
    from unittest.mock import MagicMock, patch

    from fastapi import HTTPException

    from songmaker_cli.queue_streams import QueueStreamManifest
    from songmaker_cli.sharing_api import _validate_shared_queue_manifest

    manifest = QueueStreamManifest.model_construct(
        snapshot_id="snapshot",
        scope=scope,
        scope_id="shared-resource",
        content_hash="hash",
        expires_at=datetime.now(timezone.utc),
        total_duration=0,
        tracks=[],
    )
    db = MagicMock()
    with (
        patch("songmaker_cli.sharing_api.get_playlist_by_slug", return_value=None),
        patch("songmaker_cli.sharing_api.get_album_by_slug", return_value=None),
    ):
        with pytest.raises(HTTPException) as exc_info:
            _validate_shared_queue_manifest(manifest, db)

    expected_detail = "Not found" if scope != "unexpected" else "Queue stream not found"
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == expected_detail


@pytest.mark.parametrize(
    "endpoint",
    [
        pytest.param("album-stream", id="album-stream"),
        pytest.param("song-cover", id="song-cover"),
        pytest.param("playlist-cover", id="playlist-cover"),
        pytest.param("playlist-stream", id="playlist-stream"),
    ],
)
def test_missing_shared_resources_raise_not_found(endpoint: str) -> None:
    import asyncio
    from functools import partial
    from unittest.mock import MagicMock, patch

    from fastapi import HTTPException

    from songmaker_cli.sharing_api import (
        get_shared_album_stream,
        get_shared_playlist_cover,
        get_shared_playlist_stream,
        get_shared_song_cover,
    )

    request = MagicMock()
    db = MagicMock()
    ctx = MagicMock()
    if endpoint == "album-stream":
        action = partial(get_shared_album_stream, "missing", request, db, ctx)
    elif endpoint == "song-cover":
        coroutine = get_shared_song_cover("missing", request, db=db, ctx=ctx)
        action = partial(asyncio.run, coroutine)
    elif endpoint == "playlist-cover":
        coroutine = get_shared_playlist_cover("missing", request, db=db, ctx=ctx)
        action = partial(asyncio.run, coroutine)
    else:
        action = partial(get_shared_playlist_stream, "missing", request, db, ctx)
    with (
        patch("songmaker_cli.sharing_api._check_shared_rate_limit"),
        patch("songmaker_cli.sharing_api._check_shared_stream_rate_limit"),
        patch("songmaker_cli.sharing_api.get_album_by_slug", return_value=None),
        patch("songmaker_cli.sharing_api.get_song_by_slug", return_value=None),
        patch("songmaker_cli.sharing_api.get_playlist_by_slug", return_value=None),
    ):
        with pytest.raises(HTTPException) as exc_info:
            action()

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Not found"


def test_shared_album_after_revoke(sharing_app: TestClient) -> None:
    resp = sharing_app.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]
    sharing_app.delete("/api/albums/test_album/share")

    unauthed = TestClient(sharing_app.app, cookies={})
    resp = unauthed.get(f"/shared/{slug}")
    assert resp.status_code == 404


# ── Shared audio endpoint ──────────────────────────────────────────


def test_shared_audio(sharing_app: TestClient) -> None:
    resp = sharing_app.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(sharing_app.app, cookies={})
    resp = unauthed.get(f"/shared/{slug}/audio/admin_user/g1.mp3")
    assert resp.status_code == 200


def _add_second_shared_audio_take(
    session,
    *,
    is_picked: bool,
    created_at: datetime | None = None,
) -> None:
    session.add(Generation(
        id="g2", song_id="s1", version_id="v1", generation_number=2,
        mp3_path="admin_user/g2.mp3", seed=43, is_picked=is_picked,
        created_at=created_at,
    ))


@pytest.mark.parametrize(
    ("configuration", "expected_filename", "expected_page_status"),
    [
        pytest.param("newest_of_two_picks", "admin_user/g2.mp3", 200),
        pytest.param("archived_pick", "admin_user/g2.mp3", 200),
        pytest.param("pick_without_mp3_path", "admin_user/g2.mp3", 200),
        pytest.param("no_pick_uses_latest_fallback", "admin_user/g2.mp3", 200),
        pytest.param("nothing_playable", None, 200),
        pytest.param("album_not_shared", None, 404),
        pytest.param("in_root_dot_segments", None, 200),
    ],
)
def test_shared_audio_authorization_matches_presented_share_selection(
    sharing_app: TestClient,
    configuration: str,
    expected_filename: str | None,
    expected_page_status: int,
) -> None:
    """The share payload and audio authorization select the same take."""
    ctx = sharing_app.app.state.ctx
    selected_at = datetime(2026, 1, 2, tzinfo=timezone.utc)

    with ctx.db() as session:
        first_take = session.get(Generation, "g1")
        assert first_take is not None
        if configuration == "newest_of_two_picks":
            first_take.created_at = selected_at - timedelta(days=1)
            _add_second_shared_audio_take(
                session, is_picked=True, created_at=selected_at,
            )
        elif configuration == "archived_pick":
            first_take.is_archived = True
            _add_second_shared_audio_take(session, is_picked=False)
        elif configuration == "pick_without_mp3_path":
            first_take.mp3_path = ""
            _add_second_shared_audio_take(session, is_picked=False)
        elif configuration == "no_pick_uses_latest_fallback":
            first_take.is_picked = False
            _add_second_shared_audio_take(session, is_picked=False)
        elif configuration == "nothing_playable":
            first_take.is_archived = True
        elif configuration == "album_not_shared":
            album = session.get(Album, "test_album")
            assert album is not None
            album.share_slug = "private-share"
        elif configuration == "in_root_dot_segments":
            first_take.mp3_path = "admin_user/../admin_user/g1.mp3"
        else:
            raise AssertionError(f"Unknown configuration: {configuration}")
        session.commit()

    (ctx.audio_dir / "admin_user" / "g2.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)
    if configuration == "album_not_shared":
        slug = "private-share"
    else:
        slug = sharing_app.post("/api/albums/test_album/share").json()["share_slug"]
    unauthed = TestClient(sharing_app.app, cookies={})

    shared_response = unauthed.get(f"/shared/{slug}")
    assert shared_response.status_code == expected_page_status
    if expected_filename is None:
        if expected_page_status == 200:
            assert shared_response.json()["songs"][0]["audio_url"] is None
        for filename in ("admin_user/g1.mp3", "admin_user/g2.mp3"):
            assert unauthed.get(f"/shared/{slug}/audio/{filename}").status_code == 404
        return

    audio_url = shared_response.json()["songs"][0]["audio_url"]
    assert audio_url == f"/shared/{slug}/audio/{expected_filename}"
    assert unauthed.get(audio_url).status_code == 200
    other_filename = "admin_user/g1.mp3"
    if other_filename != expected_filename:
        assert unauthed.get(f"/shared/{slug}/audio/{other_filename}").status_code == 404


def _add_shared_audio_playlist(session) -> None:
    session.add(Playlist(id="pl1", title="Shared audio playlist"))
    session.add(PlaylistEntry(
        id="pe1", playlist_id="pl1", generation_id="g1", position=1,
    ))


def _add_second_shared_audio_playlist_entry(session) -> None:
    session.add(PlaylistEntry(
        id="pe2", playlist_id="pl1", generation_id="g2", position=2,
    ))


def _percent_encoded_dot_segments(path: str) -> str:
    """Keep dot segments intact because HTTP clients normalize them before sending."""
    return path.replace("..", "%2E%2E")


def _presented_audio_urls(payload: dict, entries_key: str) -> list[str]:
    entries = payload[entries_key]
    if isinstance(entries, list):
        audio_urls = (entry["audio_url"] for entry in entries)
    else:
        audio_urls = (entries,)
    return [audio_url for audio_url in audio_urls if audio_url is not None]


def _presented_audio_filenames(payload: dict, entries_key: str) -> set[str]:
    return {
        audio_url.rsplit("/audio/", maxsplit=1)[1]
        for audio_url in _presented_audio_urls(payload, entries_key)
    }


@pytest.mark.parametrize(
    ("configuration", "expected_filenames"),
    [
        pytest.param("newest_of_two_picks", {"admin_user/g2.mp3"}),
        pytest.param("archived_pick", {"admin_user/g2.mp3"}),
        pytest.param("pick_without_mp3_path", {"admin_user/g2.mp3"}),
        pytest.param("no_pick_uses_latest_fallback", {"admin_user/g2.mp3"}),
        pytest.param("nothing_playable", set()),
        pytest.param("not_shared", set()),
        pytest.param("traversal", set()),
        pytest.param("in_root_dot_segments", set()),
    ],
)
def test_shared_song_audio_authorization_matches_presented_share_selection(
    sharing_app: TestClient,
    configuration: str,
    expected_filenames: set[str],
) -> None:
    ctx = sharing_app.app.state.ctx
    selected_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    with ctx.db() as session:
        first_take = session.get(Generation, "g1")
        assert first_take is not None
        if configuration == "newest_of_two_picks":
            first_take.created_at = selected_at - timedelta(days=1)
            _add_second_shared_audio_take(
                session, is_picked=True, created_at=selected_at,
            )
        elif configuration == "archived_pick":
            first_take.is_archived = True
            _add_second_shared_audio_take(session, is_picked=False)
        elif configuration == "pick_without_mp3_path":
            first_take.mp3_path = ""
            _add_second_shared_audio_take(session, is_picked=False)
        elif configuration == "no_pick_uses_latest_fallback":
            first_take.is_picked = False
            _add_second_shared_audio_take(session, is_picked=False)
        elif configuration == "nothing_playable":
            first_take.is_archived = True
        elif configuration == "not_shared":
            song = session.get(Song, "s1")
            assert song is not None
            song.share_slug = "private-share"
        elif configuration == "traversal":
            first_take.mp3_path = "admin_user/../../outside.mp3"
        elif configuration == "in_root_dot_segments":
            first_take.mp3_path = "admin_user/../admin_user/g1.mp3"
        else:
            raise AssertionError(f"Unknown configuration: {configuration}")
        session.commit()

    (ctx.audio_dir / "admin_user" / "g2.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)
    (ctx.audio_dir.parent / "outside.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)
    slug = (
        "private-share"
        if configuration == "not_shared"
        else sharing_app.post("/api/songs/s1/share").json()["share_slug"]
    )
    unauthed = TestClient(sharing_app.app, cookies={})
    shared_response = unauthed.get(f"/shared/song/{slug}")
    candidates = {
        "admin_user/g1.mp3",
        "admin_user/g2.mp3",
        "admin_user/../../outside.mp3",
        "admin_user/../admin_user/g1.mp3",
    }
    candidate_statuses = {
        filename: unauthed.get(
            f"/shared/song/{slug}/audio/{_percent_encoded_dot_segments(filename)}",
        ).status_code
        for filename in candidates
    }
    delivered_filenames = {
        filename for filename, status_code in candidate_statuses.items()
        if status_code == 200
    }

    assert delivered_filenames == expected_filenames
    if configuration == "not_shared":
        assert shared_response.status_code == 404
        assert all(status_code == 404 for status_code in candidate_statuses.values())
        return
    if configuration == "traversal":
        assert candidate_statuses["admin_user/../../outside.mp3"] == 404
    assert shared_response.status_code == 200
    assert all(
        unauthed.get(audio_url).status_code == 200
        for audio_url in _presented_audio_urls(shared_response.json(), "audio_url")
    )
    assert _presented_audio_filenames(shared_response.json(), "audio_url") == delivered_filenames


@pytest.mark.parametrize(
    ("configuration", "expected_filenames"),
    [
        pytest.param("newest_of_two_picks", {"admin_user/g1.mp3", "admin_user/g2.mp3"}),
        pytest.param("archived_pick", {"admin_user/g2.mp3"}),
        pytest.param("pick_without_mp3_path", {"admin_user/g2.mp3"}),
        pytest.param(
            "no_pick_uses_latest_fallback", {"admin_user/g1.mp3", "admin_user/g2.mp3"},
        ),
        pytest.param("nothing_playable", set()),
        pytest.param("not_shared", set()),
        pytest.param("traversal", set()),
        pytest.param("in_root_dot_segments", set()),
    ],
)
def test_shared_playlist_audio_authorization_matches_presented_share_selection(
    sharing_app: TestClient,
    configuration: str,
    expected_filenames: set[str],
) -> None:
    ctx = sharing_app.app.state.ctx
    with ctx.db() as session:
        _add_shared_audio_playlist(session)
        first_take = session.get(Generation, "g1")
        assert first_take is not None
        if configuration == "newest_of_two_picks":
            _add_second_shared_audio_take(session, is_picked=True)
            _add_second_shared_audio_playlist_entry(session)
        elif configuration == "archived_pick":
            first_take.is_archived = True
            _add_second_shared_audio_take(session, is_picked=False)
            _add_second_shared_audio_playlist_entry(session)
        elif configuration == "pick_without_mp3_path":
            first_take.mp3_path = ""
            _add_second_shared_audio_take(session, is_picked=False)
            _add_second_shared_audio_playlist_entry(session)
        elif configuration == "no_pick_uses_latest_fallback":
            first_take.is_picked = False
            _add_second_shared_audio_take(session, is_picked=False)
            _add_second_shared_audio_playlist_entry(session)
        elif configuration == "nothing_playable":
            first_take.is_archived = True
        elif configuration == "not_shared":
            playlist = session.get(Playlist, "pl1")
            assert playlist is not None
            playlist.share_slug = "private-share"
        elif configuration == "traversal":
            first_take.mp3_path = "admin_user/../../outside.mp3"
        elif configuration == "in_root_dot_segments":
            first_take.mp3_path = "admin_user/../admin_user/g1.mp3"
        else:
            raise AssertionError(f"Unknown configuration: {configuration}")
        session.commit()

    (ctx.audio_dir / "admin_user" / "g2.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)
    (ctx.audio_dir.parent / "outside.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)
    slug = (
        "private-share"
        if configuration == "not_shared"
        else sharing_app.post("/api/playlists/pl1/share").json()["share_slug"]
    )
    unauthed = TestClient(sharing_app.app, cookies={})
    shared_response = unauthed.get(f"/shared/playlist/{slug}")
    candidates = {
        "admin_user/g1.mp3",
        "admin_user/g2.mp3",
        "admin_user/../../outside.mp3",
        "admin_user/../admin_user/g1.mp3",
    }
    candidate_statuses = {
        filename: unauthed.get(
            f"/shared/playlist/{slug}/audio/{_percent_encoded_dot_segments(filename)}",
        ).status_code
        for filename in candidates
    }
    delivered_filenames = {
        filename for filename, status_code in candidate_statuses.items()
        if status_code == 200
    }

    assert delivered_filenames == expected_filenames
    if configuration == "not_shared":
        assert shared_response.status_code == 404
        assert all(status_code == 404 for status_code in candidate_statuses.values())
        return
    if configuration == "traversal":
        assert candidate_statuses["admin_user/../../outside.mp3"] == 404
    assert shared_response.status_code == 200
    assert all(
        unauthed.get(audio_url).status_code == 200
        for audio_url in _presented_audio_urls(shared_response.json(), "entries")
    )
    assert _presented_audio_filenames(shared_response.json(), "entries") == delivered_filenames


def _seed_shared_playlist_audio(session) -> None:
    _add_shared_audio_playlist(session)


@dataclass(frozen=True)
class SharedAudioSurface:
    share_path: str
    audio_path: str
    lookup_name: str
    query_table: str
    seed: Callable | None = None


_SHARED_AUDIO_LOOKUP_CONFIGURATIONS = [
    pytest.param(
        SharedAudioSurface(
            "/api/albums/test_album/share",
            "/shared/{slug}/audio/admin_user/g1.mp3",
            "shared_album_audio_filename_is_presented",
            "generations",
        ),
        id="album",
    ),
    pytest.param(
        SharedAudioSurface(
            "/api/songs/s1/share",
            "/shared/song/{slug}/audio/admin_user/g1.mp3",
            "shared_song_audio_filename_is_presented",
            "generations",
        ),
        id="song",
    ),
    pytest.param(
        SharedAudioSurface(
            "/api/playlists/pl1/share",
            "/shared/playlist/{slug}/audio/admin_user/g1.mp3",
            "shared_playlist_audio_filename_is_presented",
            "playlist_entries",
            _seed_shared_playlist_audio,
        ),
        id="playlist",
    ),
]


@pytest.mark.parametrize(
    "surface",
    _SHARED_AUDIO_LOOKUP_CONFIGURATIONS,
)
def test_shared_audio_lookups_run_off_the_event_loop(
    sharing_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    surface: SharedAudioSurface,
) -> None:
    import asyncio
    import threading

    import httpx

    from songmaker_cli import sharing_api

    if surface.seed is not None:
        with sharing_app.app.state.ctx.db() as session:
            surface.seed(session)
            session.commit()
    slug = sharing_app.post(surface.share_path).json()["share_slug"]
    real_lookup = getattr(sharing_api, surface.lookup_name)
    observed_threads: list[int] = []

    def _observing_lookup(db, slug: str, filename: str) -> bool:
        observed_threads.append(threading.get_ident())
        return real_lookup(db, slug, filename)

    monkeypatch.setattr(sharing_api, surface.lookup_name, _observing_lookup)

    async def _request_audio() -> tuple[int, int]:
        event_loop_thread = threading.get_ident()
        transport = httpx.ASGITransport(app=sharing_app.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver",
        ) as client:
            response = await client.get(surface.audio_path.format(slug=slug))
        return response.status_code, event_loop_thread

    status_code, event_loop_thread = asyncio.run(_request_audio())

    assert status_code == 200
    assert observed_threads
    assert observed_threads[0] != event_loop_thread


@pytest.mark.parametrize(
    "surface",
    _SHARED_AUDIO_LOOKUP_CONFIGURATIONS,
)
def test_shared_audio_lookups_issue_one_scalar_filename_query(
    sharing_app: TestClient,
    surface: SharedAudioSurface,
) -> None:
    if surface.seed is not None:
        with sharing_app.app.state.ctx.db() as session:
            surface.seed(session)
            session.commit()
    slug = sharing_app.post(surface.share_path).json()["share_slug"]
    factory = sharing_app.app.state.ctx.db
    with factory() as probe_session:
        engine = probe_session.get_bind()

    queries, handle = _count_queries(engine, "select")
    try:
        unauthed = TestClient(sharing_app.app, cookies={})
        response = unauthed.get(surface.audio_path.format(slug=slug))
    finally:
        event.remove(engine, "before_cursor_execute", handle)

    assert response.status_code == 200
    assert len(queries) == 1, f"expected one scalar filename lookup, got {queries}"
    statement, parameters = queries[0]
    normalized_statement = " ".join(statement.lower().split())
    filename_predicate = "generations.mp3_path = ?"
    assert f"from {surface.query_table}" in normalized_statement
    assert filename_predicate in normalized_statement
    filename_predicate_index = normalized_statement.index(filename_predicate)
    filename_parameter_index = normalized_statement[:filename_predicate_index].count("?")
    assert parameters[filename_parameter_index] == "admin_user/g1.mp3"
    assert "versions" not in normalized_statement


@pytest.mark.parametrize(
    "surface",
    _SHARED_AUDIO_LOOKUP_CONFIGURATIONS,
)
def test_shared_audio_lookups_authorize_canonical_missing_names_before_file_checks(
    sharing_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    surface: SharedAudioSurface,
) -> None:
    if surface.seed is not None:
        with sharing_app.app.state.ctx.db() as session:
            surface.seed(session)
            session.commit()
    slug = sharing_app.post(surface.share_path).json()["share_slug"]
    factory = sharing_app.app.state.ctx.db
    with factory() as probe_session:
        engine = probe_session.get_bind()

    queries, handle = _count_queries(engine, "select")
    checked_paths: list[Path] = []
    original_exists = Path.exists

    def record_exists(path: Path) -> bool:
        checked_paths.append(path)
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", record_exists)
    try:
        unauthed = TestClient(sharing_app.app, cookies={})
        response = unauthed.get(
            surface.audio_path.replace("g1.mp3", "missing.mp3").format(slug=slug),
        )
    finally:
        event.remove(engine, "before_cursor_execute", handle)

    assert response.status_code == 404
    assert len(queries) == 1
    assert checked_paths == []


def test_shared_audio_not_found_wrong_file(sharing_app: TestClient) -> None:
    resp = sharing_app.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(sharing_app.app, cookies={})
    resp = unauthed.get(f"/shared/{slug}/audio/nonexistent.mp3")
    assert resp.status_code == 404


def test_shared_audio_hides_path_traversal_as_a_missing_file(
    sharing_app: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    slug = sharing_app.post("/api/albums/test_album/share").json()["share_slug"]
    factory = sharing_app.app.state.ctx.db
    unauthed = TestClient(sharing_app.app, cookies={})

    with factory() as session:
        session.query(Generation).filter_by(id="g1").update({
            "mp3_path": "admin_user/../../outside.mp3",
        })
        session.commit()

    caplog.set_level(logging.WARNING, logger="songmaker_cli.audio_paths")
    traversal_response = unauthed.get(
        f"/shared/{slug}/audio/admin_user/%2E%2E/%2E%2E/outside.mp3",
    )

    with factory() as session:
        session.query(Generation).filter_by(id="g1").update({
            "mp3_path": "admin_user/missing.mp3",
        })
        session.commit()

    missing_response = unauthed.get(f"/shared/{slug}/audio/admin_user/missing.mp3")

    assert traversal_response.status_code == 404
    assert traversal_response.json()["detail"] == "Not Found"
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "Not Found"
    assert traversal_response.headers == missing_response.headers
    traversal_log = next(
        record for record in caplog.records
        if record.name == "songmaker_cli.audio_paths"
    ).getMessage()
    assert traversal_log == "Audio path traversal denied"


@pytest.mark.acceptance("ACC-SHARE-18")
def test_shared_audio_not_found_bad_slug(sharing_app: TestClient) -> None:
    unauthed = TestClient(sharing_app.app, cookies={})
    resp = unauthed.get("/shared/bad-slug/audio/admin_user/g1.mp3")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Not Found"


# ── Share payload media fields (#128) ───────────────────────────────


def _count_queries(
    engine,
    statement_contains: str,
) -> tuple[list[tuple[str, tuple]], Callable]:
    """Register a query-count probe; caller removes it via the returned handle."""
    queries: list[tuple[str, tuple]] = []

    def _record(conn, cursor, statement, parameters, context, executemany) -> None:
        if statement_contains.lower() in statement.lower():
            queries.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", _record)
    return queries, _record


def _seed_multi_track_album(session) -> None:
    admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
    session.add(admin)
    session.add(Album(id="test_album", title="Test Album", artist="Test Artist"))
    for i in range(4):
        song_id = f"s{i}"
        session.add(Song(
            id=song_id, title=f"Song {i}", album_id="test_album", track_number=i,
            slug=f"song-{i}",
        ))
        session.add(Version(
            id=f"v{i}", song_id=song_id, version_number=1,
            lyrics=f"Lyrics {i}", audio_duration=100 + i,
        ))
        session.add(Generation(
            id=f"g{i}", song_id=song_id, version_id=f"v{i}", generation_number=1,
            mp3_path=f"admin_user/g{i}.mp3", seed=1, is_picked=True,
            audio_duration_sec=100 + i,
        ))
    session.add(
        Song(
            id="s_no_pick", title="No Pick", album_id="test_album", track_number=4,
            slug="no-pick",
        ),
    )


def test_shared_album_view_includes_pick_media(tmp_path: Path) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_multi_track_album)
    login_and_csrf(client, "admin", "admin12345")
    resp = client.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(client.app, cookies={})
    data = unauthed.get(f"/shared/{slug}").json()

    songs_by_id = {song["id"]: song for song in data["songs"]}
    for i in range(4):
        song = songs_by_id[f"s{i}"]
        assert song["generation_id"] == f"g{i}"
        assert song["audio_duration"] == 100 + i
        assert song["lyrics"] == f"Lyrics {i}"

    no_pick = songs_by_id["s_no_pick"]
    assert no_pick["audio_url"] is None
    assert no_pick["generation_id"] is None
    assert no_pick["audio_duration"] is None
    assert no_pick["lyrics"] is None


def test_shared_album_view_warms_versions_in_one_query(tmp_path: Path) -> None:
    client, factory = make_test_app(tmp_path, seed_db=_seed_multi_track_album)
    login_and_csrf(client, "admin", "admin12345")
    resp = client.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]

    with factory() as probe_session:
        engine = probe_session.get_bind()

    queries, handle = _count_queries(engine, "versions")
    try:
        unauthed = TestClient(client.app, cookies={})
        resp = unauthed.get(f"/shared/{slug}")
    finally:
        event.remove(engine, "before_cursor_execute", handle)

    assert resp.status_code == 200
    assert len(resp.json()["songs"]) == 5
    assert len(queries) == 1, (
        f"expected one warm-up query for all four picks' versions, got {len(queries)}: {queries}"
    )


def _seed_song_with_pick(session) -> None:
    admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
    session.add(admin)
    session.add(Album(id="test_album", title="Test Album", artist="Test Artist"))
    session.add(
        Song(id="s1", title="Song One", album_id="test_album", track_number=1, slug="song-one"),
    )
    session.add(Version(
        id="v1", song_id="s1", version_number=1, lyrics="Hello", audio_duration=180,
    ))
    session.add(Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="admin_user/g1.mp3", seed=42, is_picked=True,
        audio_duration_sec=180.0,
    ))


def test_shared_song_view_includes_pick_media(tmp_path: Path) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_song_with_pick)
    login_and_csrf(client, "admin", "admin12345")
    resp = client.post("/api/songs/s1/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(client.app, cookies={})
    data = unauthed.get(f"/shared/song/{slug}").json()

    assert data["generation_id"] == "g1"
    assert data["audio_duration"] == 180
    assert data["lyrics"] == "Hello"


def test_shared_song_view_without_pick_returns_null_media(tmp_path: Path) -> None:
    def _seed(session) -> None:
        admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        session.add(Album(id="test_album", title="Test Album", artist="Test Artist"))
        session.add(
            Song(id="s1", title="No Pick", album_id="test_album", track_number=1, slug="no-pick"),
        )

    client, _ = make_test_app(tmp_path, seed_db=_seed)
    login_and_csrf(client, "admin", "admin12345")
    resp = client.post("/api/songs/s1/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(client.app, cookies={})
    data = unauthed.get(f"/shared/song/{slug}").json()

    assert data["audio_url"] is None
    assert data["generation_id"] is None
    assert data["audio_duration"] is None
    assert data["lyrics"] is None


def test_shared_generation_view_includes_pick_media(sharing_app: TestClient) -> None:
    resp = sharing_app.post("/api/generations/g1/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(sharing_app.app, cookies={})
    data = unauthed.get(f"/shared/gen/{slug}").json()

    assert data["generation_id"] == "g1"
    # audio_duration is the take's own measured length (#258), never the
    # requested parameter -- unmeasured is None here, not 0.
    assert data["audio_duration"] is None
    assert data["lyrics"] == "Hello"


def test_shared_song_and_generation_manifests_expose_their_album_cover(
    sharing_app: TestClient,
) -> None:
    ctx = sharing_app.app.state.ctx
    with ctx.db() as session:
        album = session.get(Album, "test_album")
        assert album is not None
        album.cover_key = "cover.png"
        session.commit()
    cover_dir = ctx.audio_dir / "covers" / "test_album"
    cover_dir.mkdir(parents=True)
    (cover_dir / "original.png").write_bytes(b"cover")
    (cover_dir / "card.jpg").write_bytes(b"cover")
    (cover_dir / "detail.jpg").write_bytes(b"cover")

    song_slug = sharing_app.post("/api/songs/s1/share").json()["share_slug"]
    generation_slug = sharing_app.post("/api/generations/g1/share").json()["share_slug"]
    unauthed = TestClient(sharing_app.app, cookies={})

    song = unauthed.get(f"/shared/song/{song_slug}").json()
    generation = unauthed.get(f"/shared/gen/{generation_slug}").json()

    assert song["album_cover"]["card"] == (
        f"/shared/song/{song_slug}/album-cover?variant=card&v=cover.png"
    )
    assert generation["album_cover"]["detail"] == (
        f"/shared/gen/{generation_slug}/album-cover?variant=detail&v=cover.png"
    )
    assert unauthed.get(song["album_cover"]["card"]).status_code == 200
    assert unauthed.get(generation["album_cover"]["detail"]).status_code == 200

    assert sharing_app.delete("/api/songs/s1/share").status_code == 200
    assert unauthed.get(f"/shared/song/{song_slug}").status_code == 404
    assert unauthed.get(song["album_cover"]["card"]).status_code == 404

    assert sharing_app.delete("/api/generations/g1/share").status_code == 200
    assert unauthed.get(f"/shared/gen/{generation_slug}").status_code == 404
    assert unauthed.get(generation["album_cover"]["detail"]).status_code == 404


def test_shared_generation_hides_a_noncanonical_stored_audio_path(
    sharing_app: TestClient,
) -> None:
    with sharing_app.app.state.ctx.db() as session:
        generation = session.get(Generation, "g1")
        assert generation is not None
        generation.mp3_path = "admin_user/../admin_user/g1.mp3"
        session.commit()

    slug = sharing_app.post("/api/generations/g1/share").json()["share_slug"]
    unauthed = TestClient(sharing_app.app, cookies={})

    response = unauthed.get(f"/shared/gen/{slug}")

    assert response.status_code == 200
    assert response.json()["audio_url"] is None
    assert unauthed.get(f"/shared/gen/{slug}/audio/admin_user/g1.mp3").status_code == 404


def test_shared_generation_manifest_uses_the_stored_canonical_path_without_resolving(
    sharing_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = sharing_app.post("/api/generations/g1/share").json()["share_slug"]

    def _fail_resolve(_path: Path, *args, **kwargs):
        raise AssertionError("share JSON must not resolve audio paths")

    monkeypatch.setattr(Path, "resolve", _fail_resolve)
    unauthed = TestClient(sharing_app.app, cookies={})

    response = unauthed.get(f"/shared/gen/{slug}")

    assert response.status_code == 200
    assert response.json()["audio_url"] == f"/shared/gen/{slug}/audio/admin_user/g1.mp3"


def test_shared_generation_audio_authorizes_canonical_missing_names_before_file_checks(
    sharing_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = sharing_app.post("/api/generations/g1/share").json()["share_slug"]
    factory = sharing_app.app.state.ctx.db
    with factory() as probe_session:
        engine = probe_session.get_bind()

    queries, handle = _count_queries(engine, "select")
    filesystem_calls: list[str] = []

    for method_name in ("resolve", "lstat", "stat", "exists"):
        original_method = getattr(Path, method_name)

        def record_filesystem_call(
            path: Path,
            *args,
            _name=method_name,
            _method=original_method,
            **kwargs,
        ):
            filesystem_calls.append(_name)
            return _method(path, *args, **kwargs)

        monkeypatch.setattr(Path, method_name, record_filesystem_call)
    try:
        unauthed = TestClient(sharing_app.app, cookies={})
        response = unauthed.get(f"/shared/gen/{slug}/audio/admin_user/missing.mp3")
    finally:
        event.remove(engine, "before_cursor_execute", handle)

    assert response.status_code == 404
    assert len(queries) == 1
    assert filesystem_calls == []


def test_shared_generation_audio_lookup_runs_off_the_event_loop(
    sharing_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import threading

    import httpx

    from songmaker_cli import sharing_api

    slug = sharing_app.post("/api/generations/g1/share").json()["share_slug"]
    real_lookup = sharing_api.get_generation_by_slug
    observed_threads: list[int] = []

    def _observing_lookup(db, shared_slug: str):
        observed_threads.append(threading.get_ident())
        return real_lookup(db, shared_slug)

    monkeypatch.setattr(sharing_api, "get_generation_by_slug", _observing_lookup)

    async def _request_audio() -> tuple[int, int]:
        event_loop_thread = threading.get_ident()
        transport = httpx.ASGITransport(app=sharing_app.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver",
        ) as client:
            response = await client.get(f"/shared/gen/{slug}/audio/admin_user/g1.mp3")
        return response.status_code, event_loop_thread

    status_code, event_loop_thread = asyncio.run(_request_audio())

    assert status_code == 200
    assert observed_threads
    assert observed_threads[0] != event_loop_thread


def test_shared_generation_reports_the_takes_measured_duration(
    sharing_app: TestClient,
) -> None:
    factory = sharing_app.app.state.ctx.db
    with factory() as session:
        gen = session.query(Generation).filter_by(id="g1").one()
        gen.audio_duration_sec = 188.0
        session.commit()

    resp = sharing_app.post("/api/generations/g1/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(sharing_app.app, cookies={})
    data = unauthed.get(f"/shared/gen/{slug}").json()

    assert data["audio_duration"] == 188.0


def _seed_playlist_with_entries(session) -> None:
    admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
    session.add(admin)
    session.add(Album(id="test_album", title="Test Album", artist="Test Artist"))
    session.add(Playlist(id="pl1", title="My Playlist"))
    for i in range(3):
        song_id = f"s{i}"
        session.add(Song(
            id=song_id, title=f"Song {i}", album_id="test_album", track_number=i,
            slug=f"song-{i}",
        ))
        session.add(Version(
            id=f"v{i}", song_id=song_id, version_number=1,
            lyrics=f"Lyrics {i}", audio_duration=100 + i,
        ))
        session.add(Generation(
            id=f"g{i}", song_id=song_id, version_id=f"v{i}", generation_number=1,
            mp3_path=f"admin_user/g{i}.mp3", seed=1,
            audio_duration_sec=100 + i,
        ))
        session.add(PlaylistEntry(id=f"e{i}", playlist_id="pl1", generation_id=f"g{i}", position=i))


def _write_cover_variants(audio_dir: Path, dirname: str, entity_id: str) -> None:
    cover_dir = audio_dir / dirname / entity_id
    cover_dir.mkdir(parents=True)
    (cover_dir / "original.png").write_bytes(b"cover")
    (cover_dir / "card.jpg").write_bytes(b"cover")
    (cover_dir / "detail.jpg").write_bytes(b"cover")


def _add_mosaic_album(session, index: int) -> str:
    album_id = f"mosaic-album-{index}"
    song_id = f"mosaic-song-{index}"
    generation_id = f"mosaic-generation-{index}"
    session.add(Album(
        id=album_id,
        title=f"Mosaic Album {index}",
        artist="Test Artist",
        cover_key=f"mosaic-{index}.png",
    ))
    session.add(Song(
        id=song_id,
        title=f"Mosaic Song {index}",
        album_id=album_id,
        track_number=1,
        slug=f"mosaic-song-{index}",
    ))
    session.add(Generation(
        id=generation_id,
        song_id=song_id,
        generation_number=1,
        mp3_path=f"admin_user/mosaic-{index}.mp3",
        seed=index,
    ))
    session.add(PlaylistEntry(
        id=f"mosaic-entry-{index}",
        playlist_id="pl1",
        generation_id=generation_id,
        position=index + 2,
    ))
    return album_id


def test_shared_playlist_view_includes_pick_media(tmp_path: Path) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_playlist_with_entries)
    login_and_csrf(client, "admin", "admin12345")
    resp = client.post("/api/playlists/pl1/share")
    slug = resp.json()["share_slug"]

    unauthed = TestClient(client.app, cookies={})
    data = unauthed.get(f"/shared/playlist/{slug}").json()

    entries_by_id = {e["entry_id"]: e for e in data["entries"]}
    for i in range(3):
        entry = entries_by_id[f"e{i}"]
        assert entry["generation_id"] == f"g{i}"
        assert entry["audio_duration"] == 100 + i
        assert entry["lyrics"] == f"Lyrics {i}"


def test_shared_playlist_page_manifest_exposes_its_own_cover_and_stream_stays_audio_only(
    tmp_path: Path,
) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_playlist_with_entries)
    login_and_csrf(client, "admin", "admin12345")
    with client.app.state.ctx.db() as session:
        playlist = session.get(Playlist, "pl1")
        assert playlist is not None
        playlist.cover_key = "playlist.png"
        session.commit()
    _write_cover_variants(client.app.state.ctx.audio_dir, PLAYLIST_COVER_DIRNAME, "pl1")

    slug = client.post("/api/playlists/pl1/share").json()["share_slug"]
    public = TestClient(client.app, cookies={})
    page_manifest = public.get(f"/shared/playlist/{slug}").json()

    assert page_manifest["cover"] == {
        "card": f"/shared/playlist/{slug}/cover?variant=card&v=playlist.png",
        "detail": f"/shared/playlist/{slug}/cover?variant=detail&v=playlist.png",
    }
    assert page_manifest["album_covers"] == []
    assert public.get(page_manifest["cover"]["detail"]).status_code == 200

    stream_manifest = public.post(f"/shared/playlist/{slug}/stream").json()
    assert "cover" not in stream_manifest
    assert "album_covers" not in stream_manifest


def test_shared_playlist_page_manifest_exposes_at_most_four_share_bound_mosaic_covers(
    tmp_path: Path,
) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_playlist_with_entries)
    login_and_csrf(client, "admin", "admin12345")
    with client.app.state.ctx.db() as session:
        first_album = session.get(Album, "test_album")
        assert first_album is not None
        first_album.cover_key = "first.png"
        mosaic_album_ids = [_add_mosaic_album(session, index) for index in range(1, 5)]
        session.commit()
    _write_cover_variants(client.app.state.ctx.audio_dir, "covers", "test_album")
    for album_id in mosaic_album_ids:
        _write_cover_variants(client.app.state.ctx.audio_dir, "covers", album_id)

    slug = client.post("/api/playlists/pl1/share").json()["share_slug"]
    public = TestClient(client.app, cookies={})
    page_manifest = public.get(f"/shared/playlist/{slug}").json()
    mosaic_urls = [cover["card"] for cover in page_manifest["album_covers"]]

    assert mosaic_urls == [
        f"/shared/playlist/{slug}/album-cover/test_album?variant=card&v=first.png",
        *[
            f"/shared/playlist/{slug}/album-cover/mosaic-album-{index}"
            f"?variant=card&v=mosaic-{index}.png"
            for index in range(1, 4)
        ],
    ]
    assert all(url.startswith(f"/shared/playlist/{slug}/") for url in mosaic_urls)
    assert "/api/albums/" not in str(page_manifest)
    assert all(public.get(url).status_code == 200 for url in mosaic_urls)


def test_shared_playlist_cover_routes_hide_unshared_foreign_and_old_keys(tmp_path: Path) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_playlist_with_entries)
    login_and_csrf(client, "admin", "admin12345")
    with client.app.state.ctx.db() as session:
        album = session.get(Album, "test_album")
        assert album is not None
        album.cover_key = "album.png"
        session.add(Album(
            id="foreign-album", title="Foreign", artist="Other", cover_key="foreign.png",
        ))
        session.commit()
    _write_cover_variants(client.app.state.ctx.audio_dir, "covers", "test_album")
    _write_cover_variants(client.app.state.ctx.audio_dir, "covers", "foreign-album")

    slug = client.post("/api/playlists/pl1/share").json()["share_slug"]
    public = TestClient(client.app, cookies={})
    page_manifest = public.get(f"/shared/playlist/{slug}").json()
    mosaic_cover = page_manifest["album_covers"][0]["detail"]

    assert public.get(mosaic_cover.replace("album.png", "old.png")).status_code == 404
    assert public.get(
        f"/shared/playlist/{slug}/album-cover/foreign-album?variant=detail&v=foreign.png",
    ).status_code == 404

    assert client.delete("/api/playlists/pl1/share").status_code == 200
    assert public.get(mosaic_cover).status_code == 404


def test_shared_playlist_view_warms_versions_in_one_query(tmp_path: Path) -> None:
    client, factory = make_test_app(tmp_path, seed_db=_seed_playlist_with_entries)
    login_and_csrf(client, "admin", "admin12345")
    resp = client.post("/api/playlists/pl1/share")
    slug = resp.json()["share_slug"]

    with factory() as probe_session:
        engine = probe_session.get_bind()

    queries, handle = _count_queries(engine, "versions")
    try:
        unauthed = TestClient(client.app, cookies={})
        resp = unauthed.get(f"/shared/playlist/{slug}")
    finally:
        event.remove(engine, "before_cursor_execute", handle)

    assert resp.status_code == 200
    assert len(resp.json()["entries"]) == 3
    assert len(queries) == 1, (
        f"expected one warm-up query for all three entries' versions, got {len(queries)}: {queries}"
    )


# ── Rate limiting ──────────────────────────────────────────────────


def test_shared_rate_limit_fails_open_when_limiter_backend_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public share page is LimiterFailurePolicy.FAIL_OPEN: a broken
    limiter (Redis down) must let real listeners through rather than 503."""
    client, _ = _make_sharing_app(tmp_path)
    login_and_csrf(client, "admin", "admin12345")
    resp = client.post("/api/albums/test_album/share")
    slug = resp.json()["share_slug"]

    class _BrokenLimiter:
        def is_allowed(self, _ip: str) -> bool:
            raise RuntimeError("redis down")

    monkeypatch.setattr(
        "songmaker_cli.sharing_api._get_shared_limiter",
        lambda _request: _BrokenLimiter(),
    )

    unauthed = TestClient(client.app, cookies={})
    resp = unauthed.get(f"/shared/{slug}")
    assert resp.status_code == 200


@contextmanager
def _shared_app_with_small_budget(
    client: TestClient, tmp_path: Path, trusted_proxies: TrustedProxies = TrustedProxies(),
):
    """An app of its own, budget 2, so one test's listeners cannot spill into
    another's. The limiter is built at app creation from SHARING_RATE_LIMIT."""
    import songmaker_cli.constants as consts
    from songmaker_cli.server import create_app

    old_limit = consts.SHARING_RATE_LIMIT
    consts.SHARING_RATE_LIMIT = 2
    try:
        audio_dir = client.app.state.ctx.audio_dir
        data_dir = client.app.state.ctx.data_dir
        ctx = AppContext(
            db=client.app.state.ctx.db,
            audio_dir=audio_dir,
            data_dir=data_dir,
            session_secret=TEST_SECRET,
            redis=make_fake_redis(),
            trusted_proxies=trusted_proxies,
        )
        yield create_app(audio_dir, data_dir, tmp_path, ctx=ctx)
    finally:
        consts.SHARING_RATE_LIMIT = old_limit


def _shared_album_slug(client: TestClient) -> str:
    login_and_csrf(client, "admin", "admin12345")
    return client.post("/api/albums/test_album/share").json()["share_slug"]


def test_shared_rate_limit(tmp_path: Path) -> None:
    client, _ = _make_sharing_app(tmp_path)
    slug = _shared_album_slug(client)

    with _shared_app_with_small_budget(client, tmp_path) as app:
        unauthed = TestClient(app, cookies={})
        for _ in range(3):
            resp = unauthed.get(f"/shared/{slug}")

    assert resp.status_code == 429


def test_shared_rate_limit_is_per_listener_behind_a_proxy(tmp_path: Path) -> None:
    """A share page is the operator's public face: one listener exhausting the
    budget must not close the page for everyone else behind the same proxy."""
    client, _ = _make_sharing_app(tmp_path)
    slug = _shared_album_slug(client)

    with _shared_app_with_small_budget(
        client, tmp_path, TrustedProxies.parse(_PROXY_NETWORK),
    ) as app:
        listener = TestClient(app, cookies={}, client=(_TRUSTED_PEER, 55000))

        def _listen(forwarded_for: str) -> int:
            return listener.get(
                f"/shared/{slug}", headers={"x-forwarded-for": forwarded_for},
            ).status_code

        for _ in range(3):
            exhausted = _listen("203.0.113.1")
        other_listener = _listen("203.0.113.2")

    assert exhausted == 429
    assert other_listener == 200


# ── Ownership checks ──────────────────────────────────────────────


def test_share_album_ownership_enforced(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import create_album, create_session, create_user
    from songmaker_cli.middleware import SESSION_COOKIE

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    factory = init_db(data_dir / "songmaker.db")
    with factory() as session:
        owner = create_user(session, "owner", hash_password("pass1234"))
        other = create_user(session, "other_user", hash_password("pass1234"))
        session.flush()
        create_album(session, "owners_album", "Owners Album", created_by=owner.id)
        expires = datetime.now(timezone.utc) + timedelta(days=30)
        other_session = create_session(session, other.id, expires)
        session.commit()
        other_sid = other_session.id

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=data_dir,
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.server import create_app
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={})
    client.cookies.set(SESSION_COOKIE, sign_session_id(other_sid, TEST_SECRET))

    from conftest import apply_csrf_header
    resp = client.post("/api/auth/login", json={"username": "other_user", "password": "pass1234"})
    apply_csrf_header(client)

    resp = client.post("/api/albums/owners_album/share")
    assert resp.status_code == 404


# ── DB query functions ─────────────────────────────────────────────


def test_enable_disable_sharing(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import (
        create_album,
        disable_album_sharing,
        enable_album_sharing,
        get_album_by_slug,
    )

    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        create_album(session, "a1", "Album")
        session.commit()

    with factory() as session:
        album = enable_album_sharing(session, "a1")
        slug = album.share_slug
        assert slug is not None
        assert album.is_shared is True
        session.commit()

    with factory() as session:
        found = get_album_by_slug(session, slug)
        assert found is not None
        assert found.id == "a1"

    with factory() as session:
        album = disable_album_sharing(session, "a1")
        assert album.share_slug is None
        assert album.is_shared is False
        session.commit()

    with factory() as session:
        found = get_album_by_slug(session, slug)
        assert found is None


def test_enable_sharing_not_found(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import enable_album_sharing

    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        with pytest.raises(ValueError, match="Album not found"):
            enable_album_sharing(session, "nonexistent")


def test_disable_sharing_not_found(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import disable_album_sharing

    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        with pytest.raises(ValueError, match="Album not found"):
            disable_album_sharing(session, "nonexistent")


# ── Share inventory ────────────────────────────────────────────────


USER_A = "user-a"
USER_B = "user-b"
ADMIN_ID = "user-admin"


def _ts(offset_seconds: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)


def _inventory_factory(tmp_path: Path):
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(id=USER_A, username="alice", password_hash="unused", role="user"))
        session.add(User(id=USER_B, username="bob", password_hash="unused", role="user"))
        session.add(User(id=ADMIN_ID, username="admin", password_hash="unused", role="admin"))
        session.flush()
        _seed_inventory(session)
        session.commit()
    return factory


def _seed_inventory(session) -> None:
    session.add(Album(
        id="alice-album", title="Alice Album", artist="Artist",
        created_by=USER_A, created_at=_ts(40),
        is_shared=True, share_slug="slug-album",
    ))
    session.add(Song(
        id="alice-song", title="Alice Song", album_id="alice-album", slug="alice-song",
        created_at=_ts(30), is_shared=True, share_slug="slug-song",
    ))
    session.add(Version(id="alice-v1", song_id="alice-song", version_number=1, lyrics="Hi"))
    session.add(Generation(
        id="alice-gen", song_id="alice-song", version_id="alice-v1",
        generation_number=1, mp3_path="alice/g1.mp3", seed=1,
        created_at=_ts(20), is_shared=True, share_slug="slug-gen",
    ))
    session.add(Playlist(
        id="alice-pl", title="Alice Playlist", created_by=USER_A,
        created_at=_ts(10), is_shared=True, share_slug="slug-pl",
    ))
    session.add(Album(
        id="bob-album", title="Bob Album", artist="Artist",
        created_by=USER_B, created_at=_ts(100),
        is_shared=True, share_slug="slug-bob",
    ))
    session.add(Album(
        id="admin-album", title="Admin Album", artist="Artist",
        created_by=ADMIN_ID, created_at=_ts(5),
        is_shared=True, share_slug="slug-admin",
    ))


def _inventory_client(tmp_path: Path, user_id: str, role: str = "user"):
    from fastapi import FastAPI

    from songmaker_cli.api import router
    from songmaker_cli.app_context import AppContext
    from songmaker_cli.middleware import AuthenticatedUser, get_current_user

    factory = _inventory_factory(tmp_path)
    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = (
        lambda: AuthenticatedUser(id=user_id, username=f"test-{user_id}", role=role, is_active=True)
    )
    app.include_router(router)
    return TestClient(app), factory


def test_share_inventory_lists_four_types_for_owner(tmp_path: Path) -> None:
    from songmaker_cli.db.models import Album, Generation, Playlist, Song
    from songmaker_cli.db.queries import list_shared_inventory

    factory = _inventory_factory(tmp_path)
    with factory() as session:
        page = list_shared_inventory(session, USER_A, offset=0, limit=50)
    assert page.total == 4
    assert page.filtered_total == 4
    assert [(type(item), item.id) for item in page.items] == [
        (Album, "alice-album"),
        (Song, "alice-song"),
        (Generation, "alice-gen"),
        (Playlist, "alice-pl"),
    ]
    assert {item.share_slug for item in page.items} == {
        "slug-album", "slug-song", "slug-gen", "slug-pl",
    }


def test_share_inventory_isolates_by_user_id(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import list_shared_inventory

    factory = _inventory_factory(tmp_path)
    with factory() as session:
        alice = list_shared_inventory(session, USER_A, offset=0, limit=50)
        bob = list_shared_inventory(session, USER_B, offset=0, limit=50)
        admin = list_shared_inventory(session, ADMIN_ID, offset=0, limit=50)
    assert {item.id for item in alice.items} == {
        "alice-album", "alice-song", "alice-gen", "alice-pl",
    }
    assert {item.id for item in bob.items} == {"bob-album"}
    assert {item.id for item in admin.items} == {"admin-album"}
    assert admin.total == 1


def test_share_inventory_excludes_soft_deleted(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import list_shared_inventory, soft_delete_album, soft_delete_song

    factory = _inventory_factory(tmp_path)
    with factory() as session:
        soft_delete_song(session, "alice-song")
        session.commit()
    with factory() as session:
        page = list_shared_inventory(session, USER_A, offset=0, limit=50)
    assert {item.id for item in page.items} == {"alice-album", "alice-pl"}
    assert page.total == 2

    with factory() as session:
        soft_delete_album(session, "alice-album")
        session.commit()
    with factory() as session:
        page = list_shared_inventory(session, USER_A, offset=0, limit=50)
    assert {item.id for item in page.items} == {"alice-pl"}
    assert page.total == 1


def test_share_inventory_includes_archived_take(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import archive_generation, list_shared_inventory

    factory = _inventory_factory(tmp_path)
    with factory() as session:
        archive_generation(session, "alice-gen")
        session.commit()
    with factory() as session:
        page = list_shared_inventory(session, USER_A, offset=0, limit=50)
    gens = [item for item in page.items if item.id == "alice-gen"]
    assert len(gens) == 1
    assert gens[0].is_archived is True
    assert page.total == 4


def test_share_inventory_pagination_total_is_unfiltered(tmp_path: Path) -> None:
    from songmaker_cli.constants import LIBRARY_ITEM_ALBUM
    from songmaker_cli.db.queries import list_shared_inventory

    factory = _inventory_factory(tmp_path)
    with factory() as session:
        first = list_shared_inventory(session, USER_A, offset=0, limit=2)
        second = list_shared_inventory(session, USER_A, offset=2, limit=2)
        albums = list_shared_inventory(
            session, USER_A, item_type=LIBRARY_ITEM_ALBUM, offset=0, limit=50,
        )
    assert first.total == 4
    assert first.filtered_total == 4
    assert len(first.items) == 2
    assert [item.id for item in first.items] == ["alice-album", "alice-song"]
    assert second.total == 4
    assert [item.id for item in second.items] == ["alice-gen", "alice-pl"]
    assert albums.total == 4
    assert albums.filtered_total == 1
    assert [item.id for item in albums.items] == ["alice-album"]


def test_share_inventory_requires_public_slug_reachability(tmp_path: Path) -> None:
    from songmaker_cli.db.queries import list_shared_inventory

    factory = _inventory_factory(tmp_path)
    with factory() as session:
        session.query(Album).filter_by(id="alice-album").update({
            "is_shared": False,
        })
        session.query(Song).filter_by(id="alice-song").update({
            "share_slug": None,
        })
        session.commit()
    with factory() as session:
        page = list_shared_inventory(session, USER_A, offset=0, limit=50)
    assert {item.id for item in page.items} == {"alice-gen", "alice-pl"}
    assert page.total == 2


def test_api_library_shares_uses_user_id_not_owner_filter(tmp_path: Path) -> None:
    admin, _ = _inventory_client(tmp_path, ADMIN_ID, role="admin")
    resp = admin.get("/api/library/shares")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert [item["id"] for item in data["items"]] == ["admin-album"]
    assert data["items"][0]["type"] == "album"
    assert data["items"][0]["public_path"] == "/share/slug-admin"


def test_api_library_shares_type_filter_does_not_change_n(tmp_path: Path) -> None:
    alice, _ = _inventory_client(tmp_path, USER_A)
    all_items = alice.get("/api/library/shares").json()
    albums = alice.get("/api/library/shares", params={"type": "album"}).json()
    takes = alice.get("/api/library/shares", params={"type": "generation"}).json()
    assert all_items["total"] == 4
    assert albums["total"] == 4
    assert takes["total"] == 4
    assert [item["type"] for item in albums["items"]] == ["album"]
    assert takes["items"][0]["type"] == "generation"
    assert takes["items"][0]["is_archived"] is False
    assert takes["items"][0]["generation_number"] == 1
    assert takes["items"][0]["public_path"] == "/share/gen/slug-gen"
    assert albums["has_more"] is False


def test_api_library_shares_paginates(tmp_path: Path) -> None:
    alice, _ = _inventory_client(tmp_path, USER_A)
    first = alice.get("/api/library/shares", params={"offset": 0, "limit": 3}).json()
    second = alice.get("/api/library/shares", params={"offset": 3, "limit": 3}).json()
    assert first["total"] == 4
    assert first["has_more"] is True
    assert len(first["items"]) == 3
    assert second["total"] == 4
    assert second["has_more"] is False
    assert [item["id"] for item in second["items"]] == ["alice-pl"]


def test_api_library_shares_rejects_unknown_type(tmp_path: Path) -> None:
    alice, _ = _inventory_client(tmp_path, USER_A)
    resp = alice.get("/api/library/shares", params={"type": "voice"})
    assert resp.status_code == 422


def test_api_library_shares_requires_auth(sharing_app: TestClient) -> None:
    unauthed = TestClient(sharing_app.app, cookies={})
    resp = unauthed.get("/api/library/shares")
    assert resp.status_code == 401


# ── Share payload cues (#138) ───────────────────────────────────────

_SUNG_CUES = [
    {
        "start": 0.0,
        "end": 3.0,
        "text": "the lantern hums",
        "words": [
            {"start": 0.0, "end": 1.0, "text": "the"},
            {"start": 1.0, "end": 2.0, "text": "lantern"},
            {"start": 2.0, "end": 3.0, "text": "hums"},
        ],
    },
]
_OTHER_TAKE_CUES = [{"start": 0.0, "end": 2.0, "text": "a different rendition"}]
# A take scored before word timestamps stores no words; the payload says so
# explicitly rather than dropping the key.
_OTHER_TAKE_CUES_PAYLOAD = [{**_OTHER_TAKE_CUES[0], "words": None}]

_SHARED_ALBUM_KEYS = {"title", "artist", "subtitle", "year", "songs", "cover"}
_SHARED_ALBUM_SONG_KEYS = {
    "id", "title", "track_number", "audio_url",
    "generation_id", "audio_duration", "lyrics", "whisper_cues",
}
_SHARED_SONG_KEYS = {
    "title", "artist", "album_title", "audio_url", "cover", "album_cover",
    "generation_id", "audio_duration", "lyrics", "whisper_cues",
}
_SHARED_GENERATION_KEYS = {
    "title", "artist", "album_title", "generation_number", "seed", "audio_url",
    "generation_id", "audio_duration", "lyrics", "whisper_cues", "album_cover",
}
_SHARED_PLAYLIST_ENTRY_KEYS = {
    "entry_id", "song_title", "artist", "generation_number", "audio_url",
    "generation_id", "audio_duration", "lyrics", "whisper_cues",
}


def _seed_song_with_two_takes(session) -> None:
    admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
    session.add(admin)
    # list_shared_inventory() (the "share overview") filters strictly on
    # Album/Playlist.created_by -- flush first so admin.id is assigned and
    # the album/playlist it seeds are real owned rows, not orphans the
    # inventory query would exclude regardless of is_shared.
    session.flush()
    session.add(
        Album(
            id="test_album",
            title="Test Album",
            artist="Test Artist",
            created_by=admin.id,
        )
    )
    session.add(
        Song(id="s1", title="Song One", album_id="test_album", track_number=1, slug="song-one"),
    )
    session.add(
        Version(
            id="v1",
            song_id="s1",
            version_number=1,
            lyrics="the lantern hums",
            audio_duration=187,
        )
    )
    session.add(Playlist(id="pl1", title="My Playlist", created_by=admin.id))
    session.add(
        Generation(
            id="g1",
            song_id="s1",
            version_id="v1",
            generation_number=1,
            mp3_path="admin_user/g1.mp3",
            seed=1,
            is_picked=True,
            whisper_text="the lantern hums",
            whisper_cues=_SUNG_CUES,
        )
    )
    session.add(
        Generation(
            id="g2",
            song_id="s1",
            version_id="v1",
            generation_number=2,
            mp3_path="admin_user/g2.mp3",
            seed=2,
            whisper_text="a different rendition",
            whisper_cues=_OTHER_TAKE_CUES,
        )
    )
    session.add(PlaylistEntry(id="e1", playlist_id="pl1", generation_id="g1", position=0))


@pytest.fixture
def two_take_app(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path, seed_db=_seed_song_with_two_takes)
    login_and_csrf(client, "admin", "admin12345")
    return client


def _share_slug(client: TestClient, path: str) -> str:
    return client.post(path).json()["share_slug"]


@pytest.mark.parametrize(
    ("share_path", "shared_path_template", "expected_cues"),
    [
        ("/api/songs/s1/share", "/shared/song/{slug}", _SUNG_CUES),
        ("/api/generations/g1/share", "/shared/gen/{slug}", _SUNG_CUES),
        ("/api/generations/g2/share", "/shared/gen/{slug}", _OTHER_TAKE_CUES_PAYLOAD),
    ],
)
def test_share_payload_carries_only_the_shared_takes_cues(
    two_take_app: TestClient,
    share_path: str,
    shared_path_template: str,
    expected_cues: list[dict],
) -> None:
    slug = _share_slug(two_take_app, share_path)

    unauthed = TestClient(two_take_app.app, cookies={})
    data = unauthed.get(shared_path_template.format(slug=slug)).json()

    assert data["whisper_cues"] == expected_cues


def test_shared_album_view_carries_the_picked_takes_cues(two_take_app: TestClient) -> None:
    slug = _share_slug(two_take_app, "/api/albums/test_album/share")

    unauthed = TestClient(two_take_app.app, cookies={})
    data = unauthed.get(f"/shared/{slug}").json()

    assert data["songs"][0]["whisper_cues"] == _SUNG_CUES


def test_shared_playlist_view_carries_the_entry_takes_cues(two_take_app: TestClient) -> None:
    slug = _share_slug(two_take_app, "/api/playlists/pl1/share")

    unauthed = TestClient(two_take_app.app, cookies={})
    data = unauthed.get(f"/shared/playlist/{slug}").json()

    assert data["entries"][0]["whisper_cues"] == _SUNG_CUES


def test_share_payloads_expose_only_the_contract_fields(two_take_app: TestClient) -> None:
    """A public listener gets the shared take's playback data and nothing else —
    no transcript, no scores, no sibling takes, no owner."""
    album_slug = _share_slug(two_take_app, "/api/albums/test_album/share")
    song_slug = _share_slug(two_take_app, "/api/songs/s1/share")
    gen_slug = _share_slug(two_take_app, "/api/generations/g1/share")
    playlist_slug = _share_slug(two_take_app, "/api/playlists/pl1/share")

    unauthed = TestClient(two_take_app.app, cookies={})
    album = unauthed.get(f"/shared/{album_slug}").json()
    song = unauthed.get(f"/shared/song/{song_slug}").json()
    generation = unauthed.get(f"/shared/gen/{gen_slug}").json()
    playlist = unauthed.get(f"/shared/playlist/{playlist_slug}").json()

    assert set(album) == _SHARED_ALBUM_KEYS
    assert set(album["songs"][0]) == _SHARED_ALBUM_SONG_KEYS
    assert set(song) == _SHARED_SONG_KEYS
    assert set(generation) == _SHARED_GENERATION_KEYS
    assert set(playlist) == {"title", "entries", "cover", "album_covers"}
    assert set(playlist["entries"][0]) == _SHARED_PLAYLIST_ENTRY_KEYS


@pytest.mark.parametrize(
    ("share_path", "cover_path"),
    [
        pytest.param(
            "/api/albums/test_album/share", "/shared/{slug}/cover", id="album",
        ),
        pytest.param(
            "/api/songs/s1/share", "/shared/song/{slug}/cover", id="song",
        ),
        pytest.param(
            "/api/generations/g1/share",
            "/shared/gen/{slug}/album-cover",
            id="generation-album",
        ),
        pytest.param(
            "/api/playlists/pl1/share", "/shared/playlist/{slug}/cover", id="playlist",
        ),
    ],
)
def test_shared_cover_endpoints_hide_missing_media(
    two_take_app: TestClient,
    share_path: str,
    cover_path: str,
) -> None:
    """A live share link never turns a missing cover file into a server error."""
    slug = _share_slug(two_take_app, share_path)
    public = TestClient(two_take_app.app, cookies={})

    response = public.get(cover_path.format(slug=slug))

    assert response.status_code == 404


# ── Public base URL (#339) ───────────────────────────────────────────
#
# Share links no longer trust request.base_url. In the Docker + Cloudflare
# Tunnel deployment, TLS terminates at the Cloudflare edge and uvicorn runs
# with proxy_headers=False (#328) so nothing rewrites the ASGI scope's
# scheme -- request.base_url reports "http" even when the request actually
# arrived over https (see auth.request_is_https(), which resolves the same
# case correctly via the trusted-proxy-verified X-Forwarded-Proto, and
# docs/security.md "Proxy trust"). PUBLIC_BASE_URL is the one, validated
# owner of "what address am I reachable at from outside" instead; all four
# share endpoints call api_helpers.resolve_public_base_url().

_FOUR_SHARE_ROUTES = [
    "/api/albums/test_album/share",
    "/api/songs/s1/share",
    "/api/generations/g1/share",
    "/api/playlists/pl1/share",
]


@pytest.mark.parametrize("share_path", _FOUR_SHARE_ROUTES)
def test_share_url_carries_https_behind_a_tls_proxy(
    two_take_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    share_path: str,
) -> None:
    """TestClient's connection is plain http -- exactly like the literal
    ASGI transport behind a TLS-terminating proxy (#328) -- yet the share
    link must carry https, because that is the configured public address."""
    from songmaker_cli.settings import get_settings

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://songmaker.example")
    get_settings.cache_clear()

    resp = two_take_app.post(share_path)

    assert resp.status_code == 200
    assert resp.json()["share_url"].startswith("https://songmaker.example/share/")


@pytest.mark.parametrize("share_path", _FOUR_SHARE_ROUTES)
def test_share_fails_named_when_public_base_url_is_unconfigured(
    two_take_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    share_path: str,
) -> None:
    """An unresolvable public address fails loudly rather than building a
    share link with a guessed (and possibly wrong) scheme."""
    from songmaker_cli.settings import get_settings

    monkeypatch.setenv("PUBLIC_BASE_URL", "")
    get_settings.cache_clear()

    resp = two_take_app.post(share_path)

    assert resp.status_code == 500
    assert "PUBLIC_BASE_URL" in resp.json()["detail"]


_FOUR_SHARE_TARGETS = [
    ("/api/albums/test_album/share", Album, "test_album"),
    ("/api/songs/s1/share", Song, "s1"),
    ("/api/generations/g1/share", Generation, "g1"),
    ("/api/playlists/pl1/share", Playlist, "pl1"),
]


@pytest.mark.parametrize(("share_path", "model_class", "entity_id"), _FOUR_SHARE_TARGETS)
def test_failed_share_leaves_the_resource_private(
    two_take_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    share_path: str,
    model_class: type,
    entity_id: str,
) -> None:
    """A share attempt that fails to resolve a public address must not leave
    the resource public (#339 finding 1). Before the fix, enable_*_sharing()
    ran and committed before resolve_public_base_url() got a chance to raise
    -- a musician who saw "Share failed" actually had their album, song,
    take, or playlist sitting world-readable with a live slug."""
    from songmaker_cli.settings import get_settings

    monkeypatch.setenv("PUBLIC_BASE_URL", "")
    get_settings.cache_clear()

    resp = two_take_app.post(share_path)
    assert resp.status_code == 500

    factory = two_take_app.app.state.ctx.db
    with factory() as session:
        entity = session.query(model_class).filter_by(id=entity_id).one()
        assert entity.is_shared is False
        assert entity.share_slug is None

    shares = two_take_app.get("/api/library/shares").json()["items"]
    assert entity_id not in {item["id"] for item in shares}


def test_share_fails_named_when_public_base_url_is_malformed(
    two_take_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUBLIC_BASE_URL", "songmaker.example")  # no scheme
    from songmaker_cli.settings import get_settings

    get_settings.cache_clear()

    resp = two_take_app.post("/api/albums/test_album/share")

    assert resp.status_code == 500
    assert "PUBLIC_BASE_URL" in resp.json()["detail"]


def test_resolve_public_base_url_strips_query_and_fragment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from songmaker_cli.api_helpers import resolve_public_base_url
    from songmaker_cli.settings import get_settings

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://songmaker.example?x=1#frag")
    get_settings.cache_clear()

    assert resolve_public_base_url() == "https://songmaker.example"


def test_resolve_public_base_url_rejects_a_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unlike a query string or fragment, a path is not discarded -- a value
    like ``https://domain/app`` means someone intended a subdirectory
    deployment, and silently dropping it would build exactly the half-link
    this function exists to prevent (#339 finding 2)."""
    from fastapi import HTTPException

    from songmaker_cli.api_helpers import resolve_public_base_url
    from songmaker_cli.settings import get_settings

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://songmaker.example/app")
    get_settings.cache_clear()

    with pytest.raises(HTTPException) as exc_info:
        resolve_public_base_url()
    assert exc_info.value.status_code == 500
    assert "PUBLIC_BASE_URL" in exc_info.value.detail


def test_resolve_public_base_url_trims_surrounding_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PUBLIC_BASE_URL=https://host<trailing space> is the single most common
    .env typo -- urlsplit would otherwise fold the space into the netloc and
    hand back a broken link with a 200 (#339 finding 2)."""
    from songmaker_cli.api_helpers import resolve_public_base_url
    from songmaker_cli.settings import get_settings

    monkeypatch.setenv("PUBLIC_BASE_URL", " https://songmaker.example \n")
    get_settings.cache_clear()

    assert resolve_public_base_url() == "https://songmaker.example"


def test_resolve_public_base_url_rejects_an_embedded_scheme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``http://https://host`` parses as scheme="http", netloc="https:" --
    a non-empty netloc that is not a host. A looser "netloc is non-empty"
    check would let this through (#339 finding 2)."""
    from fastapi import HTTPException

    from songmaker_cli.api_helpers import resolve_public_base_url
    from songmaker_cli.settings import get_settings

    monkeypatch.setenv("PUBLIC_BASE_URL", "http://https://host")
    get_settings.cache_clear()

    with pytest.raises(HTTPException) as exc_info:
        resolve_public_base_url()
    assert exc_info.value.status_code == 500
