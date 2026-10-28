"""Tests for cached queue stream snapshots."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import (
    make_authenticated_user,
    make_test_app,
    queries_without_session_auth,
    seed_session,
    web_client,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient

from songmaker_cli import audio_files
from songmaker_cli.constants import QUEUE_STREAM_UNPLAYABLE_START_DETAIL
from songmaker_cli.db.models import Album, Generation, Playlist, PlaylistEntry, Song, User, Version
from songmaker_cli.queue_streams import (
    FFMPEG_TIMEOUT_SECONDS,
    QUEUE_STREAM_DURATION_LIMIT_DETAIL,
    QUEUE_STREAM_MAX_DURATION_SECONDS,
    QueueStreamSource,
    _library_skip,
    build_queue_stream_snapshot,
    check_queue_stream_rate_limit,
    collect_library_pool_generations,
    generation_matches_pool,
    probe_audio_duration,
    queue_stream_duration_fits_ffmpeg_timeout,
    queue_stream_ffmpeg_timeout_seconds,
    run_ffmpeg_concat,
    shuffle_library_sources,
    track_source_from_generation,
)


def _seed_queue_data(session) -> None:
    owner = User(id="owner-id", username="owner")
    other = User(id="other-id", username="other")
    session.add_all([owner, other])
    session.flush()
    session.add(Album(id="a1", title="Album", artist="Artist", created_by=owner.id))
    session.add(Album(id="a2", title="Other", artist="Other", created_by=other.id))
    session.flush()
    session.add(
        Song(id="s1", title="One", album_id="a1", track_number=1, slug="one"),
    )
    session.add(
        Song(id="s2", title="Two", album_id="a1", track_number=2, slug="two"),
    )
    session.add(
        Song(id="s3", title="Other", album_id="a2", track_number=1, slug="other"),
    )
    session.flush()
    session.add(Version(id="v1", song_id="s1", version_number=1, lyrics="one"))
    session.add(Version(id="v2", song_id="s2", version_number=1, lyrics="two"))
    session.add(Version(id="v3", song_id="s3", version_number=1, lyrics="other"))
    session.flush()
    session.add(
        Generation(
            id="g1",
            song_id="s1",
            version_id="v1",
            generation_number=1,
            mp3_path="owner-id/g1.mp3",
            seed=1,
            is_picked=True,
        )
    )
    session.add(
        Generation(
            id="g2",
            song_id="s2",
            version_id="v2",
            generation_number=1,
            mp3_path="owner-id/g2.mp3",
            seed=2,
            is_picked=True,
        )
    )
    session.add(
        Generation(
            id="g3",
            song_id="s3",
            version_id="v3",
            generation_number=1,
            mp3_path="other-id/g3.mp3",
            seed=3,
            is_picked=True,
        )
    )
    playlist = Playlist(id="pl1", title="Mix", created_by=owner.id)
    session.add(playlist)
    session.add(PlaylistEntry(id="pe1", playlist_id="pl1", generation_id="g1", position=0))
    session.add(PlaylistEntry(id="pe2", playlist_id="pl1", generation_id="g1", position=1))


def _write_audio_files(root: Path) -> None:
    for owner, name in (("owner-id", "g1.mp3"), ("owner-id", "g2.mp3"), ("other-id", "g3.mp3")):
        path = root / "audio" / owner
        path.mkdir(parents=True, exist_ok=True)
        (path / name).write_bytes(b"source")


def _patch_audio_build(monkeypatch) -> None:
    import songmaker_cli.queue_streams as qs

    monkeypatch.setattr(qs, "probe_audio_duration", lambda _path: 10.0)

    def _fake_concat(_concat_path: Path, output_path: Path) -> None:
        output_path.write_bytes(b"\xff\xfb\x90\x00" * 100)

    monkeypatch.setattr(qs, "run_ffmpeg_concat", _fake_concat)


def test_probe_audio_duration_reports_what_audio_files_measures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """925_M1_D3 -- the stream builder asks audio_files for a take's length, so a
    measurement from that one owner is what the stream gets."""
    monkeypatch.setattr(audio_files, "read_audio_duration", lambda _path: 42.5)
    assert probe_audio_duration(tmp_path / "take.mp3") == 42.5


@pytest.mark.parametrize(
    ("ffmpeg_path", "failure", "expected_status", "expected_output_exists"),
    [
        pytest.param(None, None, 503, True, id="binary-is-unavailable"),
        pytest.param(
            "/usr/bin/ffmpeg",
            subprocess.TimeoutExpired(["ffmpeg"], timeout=1),
            504,
            False,
            id="build-times-out",
        ),
        pytest.param(
            "/usr/bin/ffmpeg",
            subprocess.CalledProcessError(
                1, ["ffmpeg"], stderr="invalid audio",
            ),
            422,
            False,
            id="build-fails",
        ),
    ],
)
def test_run_ffmpeg_concat_maps_build_failures_to_public_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ffmpeg_path: str | None,
    failure: Exception | None,
    expected_status: int,
    expected_output_exists: bool,
) -> None:
    """Queue builders distinguish unavailable, timed-out, and failed ffmpeg runs."""
    import songmaker_cli.queue_streams as queue_streams

    concat_path = tmp_path / "input.concat.txt"
    output_path = tmp_path / "stream.tmp.mp3"
    concat_path.write_text("file 'input.mp3'\n", encoding="utf-8")
    output_path.write_bytes(b"partial")
    monkeypatch.setattr(queue_streams.shutil, "which", lambda _name: ffmpeg_path)

    if failure is not None:
        def fail_run(*_args, **_kwargs) -> None:
            raise failure

        monkeypatch.setattr(queue_streams.subprocess, "run", fail_run)

    with pytest.raises(HTTPException) as exc_info:
        run_ffmpeg_concat(concat_path, output_path)

    assert exc_info.value.status_code == expected_status
    assert output_path.exists() is expected_output_exists


def test_queue_stream_rate_limiter_failure_is_503(monkeypatch) -> None:
    class BrokenLimiter:
        def is_allowed(self, _user_id, *, limit: int, window_seconds: int):
            raise RuntimeError("down")

    limiter = BrokenLimiter()
    monkeypatch.setattr(
        "songmaker_cli.queue_streams._get_queue_stream_limiter",
        lambda _request: limiter,
    )
    user = make_authenticated_user("owner-id", username="owner")

    with pytest.raises(HTTPException) as exc_info:
        check_queue_stream_rate_limit(object(), user)

    assert exc_info.value.status_code == 503


def _seed_versioned_lyrics(session) -> None:
    owner = User(id="owner-id", username="owner")
    session.add(owner)
    session.flush()
    session.add(Album(id="a1", title="Nachtstrom", artist="Artist", created_by=owner.id))
    session.flush()
    session.add(
        Song(id="s1", title="Tide", album_id="a1", track_number=1, slug="tide"),
    )
    session.flush()
    session.add(Version(id="v-old", song_id="s1", version_number=1, lyrics="old verse"))
    session.add(Version(id="v-new", song_id="s1", version_number=2, lyrics="latest draft"))
    session.add(Version(id="v-empty", song_id="s1", version_number=3, lyrics=""))
    session.flush()
    session.add(
        Generation(
            id="g-old",
            song_id="s1",
            version_id="v-old",
            generation_number=1,
            mp3_path="owner-id/g-old.mp3",
            seed=1,
            is_picked=True,
        )
    )
    session.add(
        Generation(
            id="g-empty",
            song_id="s1",
            version_id="v-empty",
            generation_number=2,
            mp3_path="owner-id/g-empty.mp3",
            seed=2,
        )
    )
    session.add(
        Generation(
            id="g-none",
            song_id="s1",
            version_id=None,
            generation_number=3,
            mp3_path="owner-id/g-none.mp3",
            seed=3,
        )
    )


def _shared_playlist_snapshot(client: TestClient, generation_ids: list[str]):
    with client.app.state.ctx.db() as session:
        playlist = session.get(Playlist, "snapshot-playlist")
        if playlist is None:
            generation = session.get(Generation, generation_ids[0])
            playlist = Playlist(
                id="snapshot-playlist", title="Snapshot proof", slug="snapshot-proof",
                created_by=generation.song.album.created_by,
            )
            session.add(playlist)
            session.flush()
        for entry in list(playlist.entries):
            session.delete(entry)
        session.flush()
        for position, generation_id in enumerate(generation_ids):
            session.add(PlaylistEntry(
                id=f"snapshot-entry-{position}", playlist_id=playlist.id,
                generation_id=generation_id, position=position,
            ))
        session.commit()
    share = client.post("/api/playlists/snapshot-playlist/share")
    assert share.status_code == 200
    slug = share.json()["share_slug"]
    return web_client(client.app, cookies={}).post(f"/shared/playlist/{slug}/stream")


def test_queue_stream_track_uses_generation_version_lyrics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_versioned_lyrics)
    audio_root = tmp_path / "audio" / "owner-id"
    audio_root.mkdir(parents=True, exist_ok=True)
    for name in ("g-old.mp3", "g-empty.mp3", "g-none.mp3"):
        (audio_root / name).write_bytes(b"source")
    seed_session(client, "owner")

    resp = _shared_playlist_snapshot(client, ["g-old"])
    assert resp.status_code == 200
    from songmaker_cli.queue_streams import load_queue_stream_manifest

    manifest = load_queue_stream_manifest(client.app.state.ctx, resp.json()["snapshot_id"])
    assert manifest.tracks[0].lyrics == "old verse"
    track = resp.json()["tracks"][0]
    assert track["lyrics"] is None
    assert track["album_title"] == "Nachtstrom"

    song = client.get("/api/songs/s1")
    assert song.status_code == 200
    data = song.json()
    by_id = {gen["id"]: gen for gen in data["generations"]}
    assert by_id["g-old"]["version_lyrics"] == "old verse"
    assert data["lyrics"] != "old verse"


def test_queue_stream_missing_version_lyrics_are_null(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_versioned_lyrics)
    audio_root = tmp_path / "audio" / "owner-id"
    audio_root.mkdir(parents=True, exist_ok=True)
    for name in ("g-old.mp3", "g-empty.mp3", "g-none.mp3"):
        (audio_root / name).write_bytes(b"source")
    seed_session(client, "owner")

    resp = _shared_playlist_snapshot(client, ["g-empty", "g-none"])
    assert resp.status_code == 200
    from songmaker_cli.queue_streams import load_queue_stream_manifest

    manifest = load_queue_stream_manifest(client.app.state.ctx, resp.json()["snapshot_id"])
    assert [track.lyrics for track in manifest.tracks] == [None, None]

    song = client.get("/api/songs/s1")
    by_id = {gen["id"]: gen for gen in song.json()["generations"]}
    assert by_id["g-empty"]["version_lyrics"] is None
    assert by_id["g-none"]["version_lyrics"] is None
    assert song.json()["lyrics"] is not None


def test_queue_stream_audio_reports_missing_snapshot_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")

    stream = _shared_playlist_snapshot(client, ["g1"])
    snapshot_id = stream.json()["snapshot_id"]
    (tmp_path / "data" / "queue-streams" / f"{snapshot_id}.mp3").unlink()

    audio = web_client(client.app, cookies={}).get(stream.json()["stream_url"])
    assert audio.status_code == 404


# ── DB session / build lifecycle tests ──────────────────────────────────────


@pytest.mark.parametrize("kind", ["album", "playlist"])
def test_queue_stream_build_closes_db_session_before_ffmpeg_runs(
    tmp_path: Path,
    monkeypatch,
    kind: str,
) -> None:
    """The request's DB session must be released before the (potentially
    multi-hour) ffmpeg cold build runs, so it never holds a pooled connection
    for the duration of the build."""
    import songmaker_cli.queue_streams as qs
    import songmaker_cli.sharing_api as qs_api

    captured: dict[str, object] = {}
    resolver_name = "get_album_by_slug" if kind == "album" else "get_playlist_by_slug"
    original_check = getattr(qs_api, resolver_name)

    def _capturing_check(session, slug):
        captured["session"] = session
        return original_check(session, slug)

    monkeypatch.setattr(qs_api, resolver_name, _capturing_check)
    monkeypatch.setattr(qs, "probe_audio_duration", lambda _path: 10.0)

    def _fake_concat(_concat_path: Path, output_path: Path) -> None:
        session = captured["session"]
        assert session.in_transaction() is False, (
            "DB session must be closed before the ffmpeg build runs"
        )
        output_path.write_bytes(b"\xff\xfb\x90\x00" * 100)

    monkeypatch.setattr(qs, "run_ffmpeg_concat", _fake_concat)

    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")

    share_path = "/api/albums/a1/share" if kind == "album" else "/api/playlists/pl1/share"
    slug = client.post(share_path).json()["share_slug"]
    stream_path = f"/shared/{slug}/stream" if kind == "album" else f"/shared/playlist/{slug}/stream"
    resp = web_client(client.app, cookies={}).post(stream_path)

    assert resp.status_code == 200
    assert "session" in captured


def test_queue_stream_request_no_longer_sweeps_expired_snapshots(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Cleanup used to run inline before every build; a snapshot request must
    no longer sweep an unrelated expired snapshot out of the cache -- that is
    now the periodic background loop's job (see lifecycle.py)."""
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")

    stream_dir = tmp_path / "data" / "queue-streams"
    stream_dir.mkdir(parents=True, exist_ok=True)
    stale_id = "0" * 32
    stale_manifest = stream_dir / f"{stale_id}.json"
    stale_manifest.write_text(
        json.dumps(
            {
                "snapshot_id": stale_id,
                "scope": "shared-album",
                "scope_id": "test-album",
                "content_hash": "unrelated",
                "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                "total_duration": 1.0,
                "windowed": False,
                "tracks": [],
            }
        )
    )
    (stream_dir / f"{stale_id}.mp3").write_bytes(b"stale")

    resp = _shared_playlist_snapshot(client, ["g1"])

    assert resp.status_code == 200
    assert stale_manifest.exists(), "the request path must no longer sweep expired snapshots"


def test_build_lock_entries_do_not_accumulate_across_builds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """_build_locks must not grow without bound -- each per-content-hash lock
    entry is removed once the build (or cache hit) using it has finished."""
    import songmaker_cli.queue_streams as qs

    _patch_audio_build(monkeypatch)
    client, factory = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)

    with factory() as session:
        for gen_id in ("g1", "g2"):
            gen = session.get(Generation, gen_id)
            source = track_source_from_generation(
                gen, key=gen_id, index=0, entry_id=None,
                audio_url=f"/audio/{gen.mp3_path}",
            )
            build_queue_stream_snapshot(
                client.app.state.ctx, [source],
                scope="shared-album", scope_id="test-album", stream_url="",
            )

    assert qs._build_locks == {}, "lock table must not grow with each distinct build"


def test_concurrent_builds_for_same_content_hash_do_not_race_lock_removal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Two threads racing to build the same content hash must not corrupt the
    lock table: the second thread reuses the first's result instead of
    rebuilding, and the lock entry is removed exactly once, after both are
    done -- never dropped out from under a still-waiting thread."""
    import threading
    import time

    import songmaker_cli.queue_streams as qs

    build_started = threading.Event()
    release_build = threading.Event()
    build_count = 0
    build_count_lock = threading.Lock()

    monkeypatch.setattr(qs, "probe_audio_duration", lambda _path: 10.0)

    def _slow_concat(_concat_path: Path, output_path: Path) -> None:
        nonlocal build_count
        with build_count_lock:
            build_count += 1
        build_started.set()
        assert release_build.wait(timeout=5), "test setup did not release the build in time"
        output_path.write_bytes(b"\xff\xfb\x90\x00" * 100)

    monkeypatch.setattr(qs, "run_ffmpeg_concat", _slow_concat)

    client, factory = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)

    with factory() as session:
        gen = session.get(Generation, "g1")
        source = track_source_from_generation(
            gen, key="g1", index=0, entry_id=None, audio_url=f"/audio/{gen.mp3_path}",
        )

        results: list[object] = []

        def _build() -> None:
            results.append(
                build_queue_stream_snapshot(
                    client.app.state.ctx, [source],
                    scope="shared-album", scope_id="test-album", stream_url="",
                )
            )

        first = threading.Thread(target=_build)
        second = threading.Thread(target=_build)
        first.start()
        assert build_started.wait(timeout=5), "first builder never started"
        second.start()

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            entries = list(qs._build_locks.values())
            if entries and entries[0].waiters == 2:
                break
            time.sleep(0.01)
        else:
            pytest.fail("second builder never registered as a waiter on the shared lock")

        release_build.set()
        first.join(timeout=5)
        second.join(timeout=5)

    assert build_count == 1, "the second builder must reuse the cached snapshot, not rebuild"
    assert results[0].snapshot_id == results[1].snapshot_id
    assert qs._build_locks == {}, "lock entry must be removed once both builders are done"


def test_shared_playlist_queue_stream_snapshot_and_audio(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")
    share = client.post("/api/playlists/pl1/share")
    slug = share.json()["share_slug"]
    public = web_client(client.app, cookies={})

    get_resp = public.get(f"/shared/playlist/{slug}/stream")
    assert get_resp.status_code == 405

    resp = public.post(f"/shared/playlist/{slug}/stream")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tracks"]) == 2
    assert [track["entry_id"] for track in data["tracks"]] == ["pe1", "pe2"]
    assert all(track["lyrics"] is None for track in data["tracks"])
    assert data["tracks"][0]["audio_url"].startswith(f"/shared/playlist/{slug}/audio/")
    second = public.post(f"/shared/playlist/{slug}/stream")
    assert second.status_code == 200
    assert second.json()["snapshot_id"] == data["snapshot_id"]
    audio = public.get(data["stream_url"], headers={"Range": "bytes=0-3"})
    assert audio.status_code == 206


@pytest.mark.parametrize(
    ("share_endpoint", "stream_endpoint"),
    [
        ("/api/albums/a1/share", "/shared/{slug}/stream"),
        ("/api/playlists/pl1/share", "/shared/playlist/{slug}/stream"),
    ],
)
def test_shared_stream_manifests_only_playable_takes(
    tmp_path: Path,
    monkeypatch,
    share_endpoint: str,
    stream_endpoint: str,
) -> None:
    _patch_audio_build(monkeypatch)
    client, factory = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")

    with factory() as session:
        archived = session.get(Generation, "g1")
        assert archived is not None
        archived.is_archived = True
        session.add(PlaylistEntry(
            id="pe3", playlist_id="pl1", generation_id="g2", position=2,
        ))
        session.commit()

    slug = client.post(share_endpoint).json()["share_slug"]
    public = web_client(client.app, cookies={})
    response = public.post(stream_endpoint.format(slug=slug))

    assert response.status_code == 200
    tracks = response.json()["tracks"]
    assert {track["generation_id"] for track in tracks} == {"g2"}
    assert all(public.get(track["audio_url"]).status_code == 200 for track in tracks)


@pytest.mark.parametrize(
    ("share_endpoint", "stream_endpoint"),
    [
        ("/api/albums/a1/share", "/shared/{slug}/stream"),
        ("/api/playlists/pl1/share", "/shared/playlist/{slug}/stream"),
    ],
)
def test_shared_stream_manifests_skip_noncanonical_audio_paths(
    tmp_path: Path,
    monkeypatch,
    share_endpoint: str,
    stream_endpoint: str,
) -> None:
    _patch_audio_build(monkeypatch)
    client, factory = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")

    with factory() as session:
        generation = session.get(Generation, "g1")
        assert generation is not None
        generation.mp3_path = "owner-id/../owner-id/g1.mp3"
        session.add(PlaylistEntry(
            id="pe3", playlist_id="pl1", generation_id="g2", position=2,
        ))
        session.commit()

    slug = client.post(share_endpoint).json()["share_slug"]
    public = web_client(client.app, cookies={})
    response = public.post(stream_endpoint.format(slug=slug))

    assert response.status_code == 200
    assert [track["generation_id"] for track in response.json()["tracks"]] == ["g2"]


@pytest.mark.parametrize(
    ("share_endpoint", "stream_url"),
    [
        ("/api/albums/a1/share", "/shared/{slug}/stream"),
        ("/api/playlists/pl1/share", "/shared/playlist/{slug}/stream"),
    ],
)
def test_shared_queue_stream_skips_path_traversal_like_a_missing_take(
    tmp_path: Path,
    monkeypatch,
    share_endpoint: str,
    stream_url: str,
) -> None:
    _patch_audio_build(monkeypatch)
    client, factory = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")
    slug = client.post(share_endpoint).json()["share_slug"]
    public = web_client(client.app, cookies={})

    with factory() as session:
        session.query(Generation).filter_by(id="g1").update({
            "mp3_path": "owner-id/../../outside.mp3",
        })
        session.commit()

    traversal_response = public.post(stream_url.format(slug=slug))

    with factory() as session:
        session.query(Generation).filter_by(id="g1").update({
            "mp3_path": "owner-id/missing.mp3",
        })
        session.commit()

    missing_response = public.post(stream_url.format(slug=slug))

    expected_status = 200 if "albums" in share_endpoint else 422
    assert traversal_response.status_code == expected_status
    if expected_status == 200:
        assert [track["generation_id"] for track in traversal_response.json()["tracks"]] == ["g2"]
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "Not Found"


@pytest.mark.parametrize(
    ("share_endpoint", "stream_endpoint", "invalidates"),
    [
        pytest.param(
            "/api/albums/a1/share", "/shared/{slug}/stream", "picked_take",
            id="album-pick-changes",
        ),
        pytest.param(
            "/api/playlists/pl1/share", "/shared/playlist/{slug}/stream", "playlist_entry",
            id="playlist-entry-is-removed",
        ),
    ],
)
def test_shared_queue_stream_revalidates_tracks(
    tmp_path: Path,
    monkeypatch,
    share_endpoint: str,
    stream_endpoint: str,
    invalidates: str,
) -> None:
    _patch_audio_build(monkeypatch)
    client, factory = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")
    share = client.post(share_endpoint)
    slug = share.json()["share_slug"]
    public = web_client(client.app, cookies={})

    resp = public.post(stream_endpoint.format(slug=slug))
    assert resp.status_code == 200
    data = resp.json()

    if invalidates == "picked_take":
        with factory() as session:
            session.add(Generation(
                id="g1-replacement",
                song_id="s1",
                version_id="v1",
                generation_number=2,
                mp3_path="owner-id/g1-replacement.mp3",
                seed=4,
            ))
            session.commit()
        (tmp_path / "audio" / "owner-id" / "g1-replacement.mp3").write_bytes(b"source")

        pick = client.post("/api/generations/g1-replacement/pick")
        assert pick.status_code == 200
    else:
        remove = client.delete("/api/playlists/pl1/entries/pe1")
        assert remove.status_code == 200

    audio = public.get(data["stream_url"], headers={"Range": "bytes=0-3"})

    assert audio.status_code == 404


def test_shared_playlist_queue_stream_revalidates_archived_takes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, factory = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")
    slug = client.post("/api/playlists/pl1/share").json()["share_slug"]
    public = web_client(client.app, cookies={})

    response = public.post(f"/shared/playlist/{slug}/stream")
    assert response.status_code == 200
    manifest = response.json()

    with factory() as session:
        generation = session.get(Generation, "g1")
        assert generation is not None
        generation.is_archived = True
        session.commit()

    assert public.get(manifest["tracks"][0]["audio_url"]).status_code == 404
    assert public.get(manifest["stream_url"]).status_code == 404


def test_queue_stream_cache_quota_keeps_new_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    import songmaker_cli.queue_streams as qs

    monkeypatch.setattr(qs, "QUEUE_STREAM_MAX_CACHE_BYTES", 1)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")

    resp = _shared_playlist_snapshot(client, ["g1"])

    assert resp.status_code == 200
    data = resp.json()
    audio = client.get(data["stream_url"], headers={"Range": "bytes=0-3"})
    assert audio.status_code == 206


def test_queue_stream_windowed_by_track_count(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    import songmaker_cli.queue_streams as qs

    monkeypatch.setattr(qs, "QUEUE_STREAM_MAX_TRACKS", 1)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")

    resp = _shared_playlist_snapshot(client, ["g1", "g2"])

    assert resp.status_code == 200
    data = resp.json()
    assert data["windowed"] is True
    assert len(data["tracks"]) == 1
    assert data["tracks"][0]["generation_id"] == "g1"


def test_queue_stream_accepts_duration_at_cap(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    import songmaker_cli.queue_streams as qs

    monkeypatch.setattr(qs, "QUEUE_STREAM_MAX_DURATION_SECONDS", 10)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")

    resp = _shared_playlist_snapshot(client, ["g1"])

    assert resp.status_code == 200
    assert resp.json()["total_duration"] == 10


def test_queue_stream_rejects_duration_above_cap_before_ffmpeg(
    tmp_path: Path, monkeypatch
) -> None:
    import songmaker_cli.queue_streams as qs

    concat_calls: list[object] = []
    monkeypatch.setattr(qs, "QUEUE_STREAM_MAX_DURATION_SECONDS", 15)
    monkeypatch.setattr(qs, "probe_audio_duration", lambda _path: 10.0)
    monkeypatch.setattr(
        qs,
        "run_ffmpeg_concat",
        lambda *_args, **_kwargs: concat_calls.append("ffmpeg"),
    )
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")

    response = _shared_playlist_snapshot(client, ["g1", "g2"])

    assert response.status_code == 422
    assert response.json()["detail"] == QUEUE_STREAM_DURATION_LIMIT_DETAIL
    assert concat_calls == []


def test_queue_stream_duration_cap_sets_ffmpeg_timeout() -> None:
    assert FFMPEG_TIMEOUT_SECONDS == queue_stream_ffmpeg_timeout_seconds(
        QUEUE_STREAM_MAX_DURATION_SECONDS
    )
    assert queue_stream_duration_fits_ffmpeg_timeout(QUEUE_STREAM_MAX_DURATION_SECONDS)
    assert not queue_stream_duration_fits_ffmpeg_timeout(QUEUE_STREAM_MAX_DURATION_SECONDS + 1)


def test_queue_stream_cache_identity_includes_count_windowing(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    import songmaker_cli.queue_streams as qs

    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")

    monkeypatch.setattr(qs, "QUEUE_STREAM_MAX_TRACKS", 1)
    windowed = _shared_playlist_snapshot(client, ["g1", "g2"])
    assert windowed.status_code == 200
    assert windowed.json()["windowed"] is True

    monkeypatch.setattr(qs, "QUEUE_STREAM_MAX_TRACKS", 2)
    complete = _shared_playlist_snapshot(client, ["g1"])
    assert complete.status_code == 200
    assert complete.json()["windowed"] is False
    assert complete.json()["snapshot_id"] != windowed.json()["snapshot_id"]


def test_queue_stream_not_windowed_when_within_limits(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")

    resp = _shared_playlist_snapshot(client, ["g1", "g2"])

    assert resp.status_code == 200
    assert resp.json()["windowed"] is False


def test_legacy_manifest_without_windowed_field_loads_as_unwindowed(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")

    first = _shared_playlist_snapshot(client, ["g1"])
    assert first.status_code == 200
    snapshot_id = first.json()["snapshot_id"]

    manifest_path = tmp_path / "data" / "queue-streams" / f"{snapshot_id}.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("windowed", None)
    manifest_path.write_text(json.dumps(manifest))

    second = _shared_playlist_snapshot(client, ["g1"])
    assert second.status_code == 200
    assert second.json()["windowed"] is False


def test_queue_stream_first_track_too_long_raises_422(tmp_path: Path, monkeypatch) -> None:
    import songmaker_cli.queue_streams as qs

    _patch_audio_build(monkeypatch)
    # first (and only) track duration exceeds the cap → empty window → 422
    monkeypatch.setattr(qs, "QUEUE_STREAM_MAX_DURATION_SECONDS", 5)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")

    resp = _shared_playlist_snapshot(client, ["g1"])

    assert resp.status_code == 422


# ── Library stream tests ────────────────────────────────────────────────────


def _seed_library_data(session) -> None:
    """Seed two users with albums + songs that exercise all library-stream cases.

    User A (user-a):
      Album a1 (track order: s1, s2):
        s1: gen g1 (not picked, non-archived), gen g1b (picked, non-archived)
            → library picks g1b (picked preferred)
        s2: gen g2 (kept, not picked, non-archived)
            → mix includes g2 as a keep
      Album a2 (track order: s3, s4):
        s3: gen g3 (not picked, IS archived)
            → no eligible generation → skipped
        s4: no generations
            → skipped

    User B (user-b):
      Album a3: s5 with gen g5 (picked, non-archived)
    """
    user_a = User(id="user-a", username="usera")
    user_b = User(id="user-b", username="userb")
    session.add_all([user_a, user_b])
    session.flush()

    session.add(Album(id="a1", title="First", artist="A", created_by="user-a"))
    session.add(Album(id="a2", title="Second", artist="A", created_by="user-a"))
    session.add(Album(id="a3", title="B Album", artist="B", created_by="user-b"))
    session.flush()

    session.add(
        Song(id="s1", title="One", album_id="a1", track_number=1, slug="one"),
    )
    session.add(
        Song(id="s2", title="Two", album_id="a1", track_number=2, slug="two"),
    )
    session.add(
        Song(id="s3", title="Three", album_id="a2", track_number=1, slug="three"),
    )
    session.add(
        Song(id="s4", title="Four", album_id="a2", track_number=2, slug="four"),
    )
    session.add(
        Song(id="s5", title="Five", album_id="a3", track_number=1, slug="five"),
    )
    session.flush()

    session.add(Version(id="v1", song_id="s1", version_number=1, lyrics=""))
    session.add(Version(id="v2", song_id="s2", version_number=1, lyrics=""))
    session.add(Version(id="v3", song_id="s3", version_number=1, lyrics=""))
    session.add(Version(id="v5", song_id="s5", version_number=1, lyrics=""))
    session.flush()

    # s1: non-picked gen first (by created_at desc: g1b > g1), g1b is picked
    session.add(
        Generation(
            id="g1",
            song_id="s1",
            version_id="v1",
            generation_number=1,
            mp3_path="user-a/g1.mp3",
            seed=1,
            is_picked=False,
        )
    )
    session.add(
        Generation(
            id="g1b",
            song_id="s1",
            version_id="v1",
            generation_number=2,
            mp3_path="user-a/g1b.mp3",
            seed=2,
            is_picked=True,
        )
    )
    # s2: kept, not picked — mix includes it; picks does not
    session.add(
        Generation(
            id="g2",
            song_id="s2",
            version_id="v2",
            generation_number=1,
            mp3_path="user-a/g2.mp3",
            seed=3,
            is_picked=False,
            is_kept=True,
        )
    )
    # s3: single archived gen → song has no eligible generation
    session.add(
        Generation(
            id="g3",
            song_id="s3",
            version_id="v3",
            generation_number=1,
            mp3_path="user-a/g3.mp3",
            seed=4,
            is_picked=False,
            is_archived=True,
        )
    )
    # s4: no generations at all
    # s5 (user B)
    session.add(
        Generation(
            id="g5",
            song_id="s5",
            version_id="v5",
            generation_number=1,
            mp3_path="user-b/g5.mp3",
            seed=5,
            is_picked=True,
        )
    )


def _write_library_audio_files(root: Path) -> None:
    """Write audio stubs for the non-archived, eligible generations only."""
    for owner, name in (
        ("user-a", "g1.mp3"),
        ("user-a", "g1b.mp3"),
        ("user-a", "g2.mp3"),
        ("user-b", "g5.mp3"),
    ):
        path = root / "audio" / owner
        path.mkdir(parents=True, exist_ok=True)
        (path / name).write_bytes(b"source")


def test_library_pool_queue_order_and_tracks(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={})

    assert resp.status_code == 200
    data = resp.json()
    # s3 (archived gen) and s4 (no gens) are skipped → only s1 and s2 appear
    assert [t["generation_id"] for t in data["takes"]] == ["g1b", "g2"]
    # album a1 comes before a2; within a1, track 1 before track 2
    assert data["takes"][0]["song_id"] == "s1"
    assert data["takes"][1]["song_id"] == "s2"
    assert data["skipped_complete"] is True


def test_library_pool_queue_picks_picked_over_first(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={})

    assert resp.status_code == 200
    # s1 has both g1 (not picked) and g1b (picked); library must choose g1b
    s1_track = next(t for t in resp.json()["takes"] if t["song_id"] == "s1")
    assert s1_track["generation_id"] == "g1b"


def test_library_pool_queue_excludes_archived_generations(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={})

    assert resp.status_code == 200
    song_ids = [t["song_id"] for t in resp.json()["takes"]]
    assert "s3" not in song_ids  # s3's only gen is archived


def test_library_pool_queue_skips_songs_without_playable_generations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={})

    assert resp.status_code == 200
    song_ids = [t["song_id"] for t in resp.json()["takes"]]
    assert "s4" not in song_ids  # s4 has no generations at all


def test_library_pool_queue_rotation_via_start_generation_id(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"start_generation_id": "g2"})

    assert resp.status_code == 200
    data = resp.json()
    # Rotation puts g2's song first; g1b's song wraps to the end
    assert [t["generation_id"] for t in data["takes"]] == ["g2", "g1b"]


def test_library_pool_queue_start_take_is_the_clicked_generation(
    tmp_path: Path, monkeypatch,
) -> None:
    """The selected take leads the pool even when another take is picked."""
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"start_generation_id": "g1"})

    assert resp.status_code == 200
    tracks = resp.json()["takes"]
    assert tracks[0]["song_id"] == "s1"
    assert tracks[0]["generation_id"] == "g1"
    assert [t["generation_id"] for t in tracks] == ["g1", "g1b", "g2"]


def _seed_library_with_escaping_take(session) -> None:
    _seed_library_data(session)
    session.get(Generation, "g2").mp3_path = "../outside.mp3"


def _library_answer(response) -> tuple[list[str], list[tuple[str, str]]]:
    data = response.json()
    taken = [t["generation_id"] for t in data["takes"]]
    skipped = [(s["generation_id"], s["reason"]) for s in data["skipped"]]
    return taken, skipped


def test_library_scan_skips_a_take_escaping_the_audio_root_as_missing(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_with_escaping_take)
    _write_library_audio_files(tmp_path)
    (tmp_path / "outside.mp3").write_bytes(b"outside")
    seed_session(client, "usera")

    response = client.get("/api/library/pool-queue")

    assert response.status_code == 200
    taken, skipped = _library_answer(response)
    assert taken == ["g1b"]
    assert ("g2", "missing_file") in skipped


def test_library_scan_refuses_a_start_take_escaping_the_audio_root(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_with_escaping_take)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    response = client.get("/api/library/pool-queue", params={"start_generation_id": "g2"})

    assert response.status_code == 422
    assert response.json()["detail"] == QUEUE_STREAM_UNPLAYABLE_START_DETAIL


def test_library_pool_queue_start_generation_id_not_found_returns_404(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"start_generation_id": "nonexistent-id"})

    assert resp.status_code == 404


def test_library_pool_queue_start_generation_id_owned_by_other_user_returns_404(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"start_generation_id": "g5"})

    assert resp.status_code == 404


def test_library_pool_queue_archived_start_generation_returns_422(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"start_generation_id": "g3"})

    assert resp.status_code == 422
    assert resp.json()["detail"] == QUEUE_STREAM_UNPLAYABLE_START_DETAIL


def test_library_pool_queue_returns_one_more_than_track_limit(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    import songmaker_cli.queue_streams as qs

    monkeypatch.setattr(qs, "QUEUE_STREAM_MAX_TRACKS", 1)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={})

    assert resp.status_code == 200
    data = resp.json()
    assert data["skipped_complete"] is True
    assert len(data["takes"]) == 2


def _seed_large_library(session, *, song_count: int) -> None:
    """One user, one album, ``song_count`` songs each with one playable take."""
    user = User(id="user-a", username="usera")
    session.add(user)
    session.flush()
    session.add(Album(id="a1", title="Big Album", artist="A", created_by=user.id))
    session.flush()
    for i in range(song_count):
        song_id = f"s{i}"
        session.add(Song(id=song_id, title=song_id, album_id="a1", track_number=i, slug=song_id))
        session.add(Version(id=f"v{i}", song_id=song_id, version_number=1, lyrics=""))
        session.add(Generation(
            id=f"g{i}", song_id=song_id, version_id=f"v{i}", generation_number=1,
            mp3_path=f"user-a/g{i}.mp3", seed=i,
        ))


def _write_large_library_audio_files(root: Path, *, song_count: int) -> None:
    audio_dir = root / "audio" / "user-a"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for i in range(song_count):
        (audio_dir / f"g{i}.mp3").write_bytes(b"source")


def test_library_pool_queue_query_count_is_constant_not_per_song(
    tmp_path: Path, monkeypatch,
) -> None:
    """#340: resolve_library_pool_membership() must load every song's
    generations in one bulk query, not one lazy query per song."""
    from collections.abc import Callable

    from sqlalchemy import event

    song_count = 50
    _patch_audio_build(monkeypatch)
    client, factory = make_test_app(
        tmp_path, seed_db=lambda s: _seed_large_library(s, song_count=song_count),
    )
    _write_large_library_audio_files(tmp_path, song_count=song_count)
    seed_session(client, "usera")

    with factory() as probe_session:
        engine = probe_session.get_bind()

    queries: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany) -> None:
        queries.append(statement)

    handle: Callable = _record
    event.listen(engine, "before_cursor_execute", handle)
    try:
        resp = client.get("/api/library/pool-queue?pool=all")
    finally:
        event.remove(engine, "before_cursor_execute", handle)

    queries = queries_without_session_auth(queries)
    assert resp.status_code == 200
    assert len(resp.json()["takes"]) == song_count
    generation_queries = [q for q in queries if "from generations" in q.lower()]
    assert len(generation_queries) == 1, (
        f"expected one bulk generations query regardless of song count, "
        f"got {len(generation_queries)} for {song_count} songs: {generation_queries}"
    )
    # Fixed budget for GET /api/library/pool-queue against this fixture: one
    # SELECT for the page of songs (+versions +album via joinedload), one
    # selectinload SELECT for all of their generations (+version +song
    # +album) -- never a query per song. Pinned as an exact count rather
    # than "< song_count" so a regression that adds one query per some
    # OTHER relationship (not caught by the generations-only assertion
    # above) still fails loudly instead of passing at 49 of 50.
    assert len(queries) == 2, (
        f"expected exactly 2 queries for GET /api/library/pool-queue against "
        f"{song_count} songs (page of songs + bulk generations selectinload), "
        f"got {len(queries)} total queries: {queries}"
    )


def test_library_pool_queue_empty_playable_library_is_422(tmp_path: Path, monkeypatch) -> None:
    """Songs with only archived or missing generations make an honest 422, not an empty pool."""

    def seed_unplayable(session) -> None:
        _seed_library_data(session)
        from songmaker_cli.db.models import Generation

        for gen in session.query(Generation).filter(Generation.id.in_(["g1", "g1b", "g2"])):
            gen.is_archived = True
        session.flush()

    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=seed_unplayable)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={})

    assert resp.status_code == 422


def test_library_pool_queue_cross_user_isolation(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    resp_a = client.get("/api/library/pool-queue", params={})
    assert resp_a.status_code == 200
    gen_ids_a = {t["generation_id"] for t in resp_a.json()["takes"]}
    # User A's library contains only their own generations
    assert gen_ids_a == {"g1b", "g2"}

    client_b = web_client(client.app, cookies={})
    seed_session(client_b, "userb")

    resp_b = client_b.get("/api/library/pool-queue", params={})
    assert resp_b.status_code == 200
    gen_ids_b = {t["generation_id"] for t in resp_b.json()["takes"]}
    # User B's library contains only their own generation
    assert gen_ids_b == {"g5"}
    assert gen_ids_a.isdisjoint(gen_ids_b)


def test_expired_queue_stream_snapshot_is_rejected(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")
    resp = _shared_playlist_snapshot(client, ["g1"])
    data = resp.json()
    manifest_path = tmp_path / "data" / "queue-streams" / f"{data['snapshot_id']}.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    manifest_path.write_text(json.dumps(manifest))

    audio = client.get(data["stream_url"])

    assert audio.status_code == 404


@pytest.mark.parametrize(
    "snapshot_id",
    [
        pytest.param("not-a-snapshot-id", id="non-hex"),
        pytest.param("..", id="dot-segment"),
        pytest.param("0" * 32, id="unknown-hex"),
    ],
)
def test_queue_stream_audio_rejects_unknown_snapshot_ids(
    tmp_path: Path,
    snapshot_id: str,
) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    seed_session(client, "owner")

    audio = client.get(f"/shared/queue-streams/{snapshot_id}/audio")

    assert audio.status_code == 404


def test_crashed_json_tmp_file_cleaned_up_as_orphan(tmp_path: Path, monkeypatch) -> None:
    """A leftover .json.tmp file from a crashed QueueStreamManifest.save must be
    recognised as belonging to its (orphaned) snapshot and removed by the sweep.

    The real scenario: QueueStreamManifest.save crashed before the rename, so
    the .json manifest was never written. The snapshot_id is therefore not
    live and the .json.tmp file is a plain orphan.
    """
    import os
    import time
    import uuid

    from songmaker_cli.queue_streams import (
        QUEUE_STREAM_ORPHAN_MAX_AGE,
        cleanup_expired_queue_streams,
    )

    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)

    # Plant a .json.tmp file for a snapshot that was never fully written (no .json exists)
    orphan_id = uuid.uuid4().hex
    stream_dir = tmp_path / "data" / "queue-streams"
    stream_dir.mkdir(parents=True, exist_ok=True)
    stale_tmp = stream_dir / f"{orphan_id}.json.tmp"
    stale_tmp.write_text("{}", encoding="utf-8")
    old_mtime = time.time() - QUEUE_STREAM_ORPHAN_MAX_AGE.total_seconds() - 1
    os.utime(stale_tmp, (old_mtime, old_mtime))

    cleanup_expired_queue_streams(client.app.state.ctx)

    assert not stale_tmp.exists(), ".json.tmp orphan must be removed by the sweep"


def test_unreadable_manifest_json_is_ignored(tmp_path: Path) -> None:
    from songmaker_cli.queue_streams import QueueStreamManifest

    missing = tmp_path / "missing.json"
    assert QueueStreamManifest.load(missing) is None

    garbage = tmp_path / "garbage.json"
    garbage.write_text("{not-json", encoding="utf-8")
    assert QueueStreamManifest.load(garbage) is None

    not_object = tmp_path / "list.json"
    not_object.write_text("[]", encoding="utf-8")
    assert QueueStreamManifest.load(not_object) is None

    bad_expiry = tmp_path / "expiry.json"
    bad_expiry.write_text('{"expires_at": "not-a-date"}', encoding="utf-8")
    assert QueueStreamManifest.load(bad_expiry) is None, (
        "an unparseable expires_at alongside other missing required fields "
        "must fail validation, not silently produce a partial manifest"
    )


@pytest.mark.parametrize(
    "corrupt_manifest_text",
    [
        pytest.param('{"snapshot_id": "abc"}', id="missing_required_fields"),
        pytest.param("{not-json", id="malformed_json"),
    ],
)
def test_corrupt_manifest_file_returns_404_not_500(
    tmp_path: Path, monkeypatch, corrupt_manifest_text: str
) -> None:
    """A manifest file that fails to parse or is missing a required field (a
    truncated write, disk corruption) must surface as a clean 404 -- never a
    raw KeyError/500 from indexing into an unvalidated dict."""
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")

    resp = _shared_playlist_snapshot(client, ["g1"])
    assert resp.status_code == 200
    snapshot_id = resp.json()["snapshot_id"]
    manifest_path = tmp_path / "data" / "queue-streams" / f"{snapshot_id}.json"
    manifest_path.write_text(corrupt_manifest_text, encoding="utf-8")

    audio = client.get(f"/shared/queue-streams/{snapshot_id}/audio", headers={"Range": "bytes=0-3"})

    assert audio.status_code == 404


def test_cleanup_deletes_corrupt_manifest(tmp_path: Path, monkeypatch) -> None:
    import uuid

    from songmaker_cli.queue_streams import cleanup_expired_queue_streams

    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    stream_dir = tmp_path / "data" / "queue-streams"
    stream_dir.mkdir(parents=True, exist_ok=True)
    corrupt = stream_dir / f"{uuid.uuid4().hex}.json"
    corrupt.write_text("{not-json", encoding="utf-8")

    cleanup_expired_queue_streams(client.app.state.ctx)

    assert not corrupt.exists()


def _expired_shared_snapshot_with_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, Path]:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")
    slug = client.post("/api/playlists/pl1/share").json()["share_slug"]
    public = web_client(client.app, cookies={})
    stream = public.post(f"/shared/playlist/{slug}/stream")
    assert stream.status_code == 200
    snapshot_id = stream.json()["snapshot_id"]
    manifest_path = tmp_path / "data" / "queue-streams" / f"{snapshot_id}.json"
    manifest = json.loads(manifest_path.read_text())
    now = datetime.now(timezone.utc)
    manifest["expires_at"] = (now - timedelta(seconds=1)).isoformat()
    manifest["pinned"] = True
    manifest["pinned_at"] = now.isoformat()
    manifest_path.write_text(json.dumps(manifest))
    return public, manifest_path


def test_expired_snapshot_whose_manifest_still_says_pinned_is_swept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1859_R1 -- an expired manifest that still says pinned is swept like any other."""
    from songmaker_cli.queue_streams import cleanup_expired_queue_streams

    public, manifest_path = _expired_shared_snapshot_with_pin(tmp_path, monkeypatch)

    cleanup_expired_queue_streams(public.app.state.ctx)

    assert not manifest_path.exists()
    assert not manifest_path.with_suffix(".mp3").exists()


def test_expired_snapshot_whose_manifest_still_says_pinned_is_not_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1859_R1 -- an expired manifest that still says pinned is not served."""
    public, manifest_path = _expired_shared_snapshot_with_pin(tmp_path, monkeypatch)

    assert public.get(f"/shared/queue-streams/{manifest_path.stem}/audio").status_code == 404


@pytest.mark.parametrize("method", [pytest.param("post"), pytest.param("delete")])
def test_the_pin_routes_are_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    """1859_R1 -- the pin addresses answer like any unknown address."""
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    seed_session(client, "owner")
    snapshot_id = "opaque-snapshot"

    pin = getattr(client, method)(f"/api/queue-streams/{snapshot_id}/pin")
    unknown = getattr(client, method)(f"/api/queue-streams/{snapshot_id}/no-such-route")

    assert (pin.status_code, pin.json()) == (unknown.status_code, unknown.json())


def _reverse_in_place(items: list) -> None:
    items.reverse()


def _source_with_id(generation_id: str) -> QueueStreamSource:
    generation = Generation(
        id=generation_id,
        song_id="s1",
        generation_number=1,
        mp3_path=f"{generation_id}.mp3",
        seed=1,
    )
    return QueueStreamSource(
        key=generation_id,
        index=0,
        entry_id=None,
        generation=generation,
        audio_url=f"/audio/{generation_id}.mp3",
    )


def test_shuffle_library_sources_pins_start_and_mixes_rest() -> None:
    sources = [_source_with_id(gid) for gid in ("g-a", "g-b", "g-c", "g-d")]
    mixed = shuffle_library_sources(sources, "g-b", shuffle_seq=_reverse_in_place)
    assert [item.generation.id for item in mixed] == ["g-b", "g-d", "g-c", "g-a"]


def test_shuffle_library_sources_deduplicates_generation_ids() -> None:
    sources = [_source_with_id(gid) for gid in ("g-a", "g-b", "g-a", "g-c")]
    mixed = shuffle_library_sources(sources, "g-b", shuffle_seq=_reverse_in_place)
    assert [item.generation.id for item in mixed] == ["g-b", "g-c", "g-a"]


def test_shuffle_library_sources_without_start_mixes_the_full_pool() -> None:
    sources = [_source_with_id(gid) for gid in ("g-a", "g-b", "g-c")]
    mixed = shuffle_library_sources(sources, None, shuffle_seq=_reverse_in_place)
    assert [item.generation.id for item in mixed] == ["g-c", "g-b", "g-a"]


def test_shuffle_library_sources_leaves_a_single_track_unchanged() -> None:
    sources = [_source_with_id("g-a"), _source_with_id("g-a")]
    mixed = shuffle_library_sources(sources, "g-a", shuffle_seq=_reverse_in_place)
    assert [item.generation.id for item in mixed] == ["g-a"]


def _seed_library_shuffle_data(session) -> None:
    session.add(User(id="user-a", username="usera"))
    session.flush()
    session.add(Album(id="a1", title="Album", artist="A", created_by="user-a"))
    session.flush()
    for index in range(1, 5):
        session.add(
            Song(
                id=f"s{index}", title=f"Song {index}", album_id="a1",
                track_number=index, slug=f"song-{index}",
            ),
        )
    session.flush()
    for index in range(1, 5):
        session.add(Version(id=f"v{index}", song_id=f"s{index}", version_number=1, lyrics=""))
    session.flush()
    for index in range(1, 5):
        session.add(
            Generation(
                id=f"g{index}",
                song_id=f"s{index}",
                version_id=f"v{index}",
                generation_number=1,
                mp3_path=f"user-a/g{index}.mp3",
                seed=index,
                is_picked=True,
            )
        )


def _write_shuffle_audio_files(root: Path) -> None:
    path = root / "audio" / "user-a"
    path.mkdir(parents=True, exist_ok=True)
    for index in range(1, 5):
        (path / f"g{index}.mp3").write_bytes(b"source")


def test_library_pool_queue_without_shuffle_keeps_album_track_order(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_shuffle_data)
    _write_shuffle_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"shuffle": False})

    assert resp.status_code == 200
    assert [track["generation_id"] for track in resp.json()["takes"]] == [
        "g1",
        "g2",
        "g3",
        "g4",
    ]


def test_library_pool_queue_shuffle_uses_injected_rng(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    monkeypatch.setattr("songmaker_cli.queue_streams.random.shuffle", _reverse_in_place)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_shuffle_data)
    _write_shuffle_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get(
        "/api/library/pool-queue", params={"shuffle": True, "start_generation_id": "g2"},
    )

    assert resp.status_code == 200
    assert [track["generation_id"] for track in resp.json()["takes"]] == [
        "g2",
        "g4",
        "g3",
        "g1",
    ]


def test_library_pool_queue_scan_is_bounded_and_marks_unscanned_tail(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_audio_build(monkeypatch)
    import songmaker_cli.queue_streams as queue_streams

    monkeypatch.setattr(queue_streams, "LIBRARY_QUEUE_STREAM_SCAN_LIMIT", 2)
    monkeypatch.setattr(queue_streams, "QUEUE_STREAM_MAX_TRACKS", 5)
    original_skip = queue_streams._library_skip
    scanned: list[str] = []

    def recording_skip(ctx, generation):
        scanned.append(generation.id)
        return original_skip(ctx, generation)

    monkeypatch.setattr(queue_streams, "_library_skip", recording_skip)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_shuffle_data)
    _write_shuffle_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"shuffle": False})

    assert resp.status_code == 200
    assert scanned == ["g1", "g2"]
    assert [track["generation_id"] for track in resp.json()["takes"]] == [
        "g1",
        "g2",
    ]
    assert resp.json()["skipped_complete"] is False


def test_library_pool_queue_default_scan_limit_is_explicitly_partial(
    tmp_path: Path, monkeypatch
) -> None:
    import songmaker_cli.queue_streams as queue_streams

    assert queue_streams.LIBRARY_QUEUE_STREAM_SCAN_LIMIT == 1_000
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_shuffle_data)
    seed_session(client, "usera")
    album = Album(id="scan-album", title="Scan", artist="A", created_by="user-a")
    songs: list[Song] = []
    for index in range(1, 1_002):
        song = Song(
            id=f"scan-song-{index:04d}",
            title=f"Song {index}",
            album=album,
            album_id=album.id,
            track_number=index,
        )
        song.generations.append(
            Generation(
                id=f"scan-gen-{index:04d}",
                song_id=song.id,
                generation_number=1,
                mp3_path=f"user-a/scan-{index:04d}.mp3",
                model_mode="turbo",
                is_archived=False,
                is_picked=True,
                is_kept=False,
            )
        )
        songs.append(song)

    scanned: list[str] = []

    def recording_skip(_ctx, generation):
        scanned.append(generation.id)
        if generation.id == "scan-gen-1001":
            return queue_streams.QueueStreamSkipResponse(
                song_id=generation.song_id,
                generation_id=generation.id,
                reason="missing_file",
            )
        return None

    monkeypatch.setattr(queue_streams, "QUEUE_STREAM_MAX_TRACKS", 1_500)
    monkeypatch.setattr(queue_streams, "list_songs", lambda *_args, **_kwargs: songs)
    monkeypatch.setattr(queue_streams, "_library_skip", recording_skip)

    resp = client.get("/api/library/pool-queue", params={"shuffle": False})

    assert resp.status_code == 200
    assert len(scanned) == 1_000
    assert scanned[-1] == "scan-gen-1000"
    assert "scan-gen-1001" not in scanned
    assert len(resp.json()["takes"]) == 1_000
    assert resp.json()["skipped_complete"] is False
    assert resp.json()["skipped"] == []


def test_library_pool_queue_scan_stops_after_one_more_than_track_limit(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_audio_build(monkeypatch)
    import songmaker_cli.queue_streams as queue_streams

    monkeypatch.setattr(queue_streams, "LIBRARY_QUEUE_STREAM_SCAN_LIMIT", 10)
    monkeypatch.setattr(queue_streams, "QUEUE_STREAM_MAX_TRACKS", 1)
    original_skip = queue_streams._library_skip
    scanned: list[str] = []

    def recording_skip(ctx, generation):
        scanned.append(generation.id)
        return original_skip(ctx, generation)

    monkeypatch.setattr(queue_streams, "_library_skip", recording_skip)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_shuffle_data)
    _write_shuffle_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"shuffle": False})

    assert resp.status_code == 200
    assert scanned == ["g1", "g2"]
    assert [track["generation_id"] for track in resp.json()["takes"]] == ["g1", "g2"]
    assert resp.json()["skipped_complete"] is False


def test_library_pool_queue_shuffles_before_bounded_scan(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    import songmaker_cli.queue_streams as queue_streams

    monkeypatch.setattr(queue_streams, "LIBRARY_QUEUE_STREAM_SCAN_LIMIT", 1)
    monkeypatch.setattr(queue_streams, "QUEUE_STREAM_MAX_TRACKS", 5)
    monkeypatch.setattr(queue_streams.random, "shuffle", _reverse_in_place)
    original_skip = queue_streams._library_skip
    scanned: list[str] = []

    def recording_skip(ctx, generation):
        scanned.append(generation.id)
        return original_skip(ctx, generation)

    monkeypatch.setattr(queue_streams, "_library_skip", recording_skip)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_shuffle_data)
    _write_shuffle_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"shuffle": True})

    assert resp.status_code == 200
    assert scanned == ["g4"]
    assert [track["generation_id"] for track in resp.json()["takes"]] == ["g4"]
    assert resp.json()["skipped_complete"] is False


def test_library_pool_queue_start_is_first_and_scanned_once_with_small_budget(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_audio_build(monkeypatch)
    import songmaker_cli.queue_streams as queue_streams

    monkeypatch.setattr(queue_streams, "LIBRARY_QUEUE_STREAM_SCAN_LIMIT", 1)
    monkeypatch.setattr(queue_streams, "QUEUE_STREAM_MAX_TRACKS", 5)
    original_skip = queue_streams._library_skip
    scanned: list[str] = []

    def recording_skip(ctx, generation):
        scanned.append(generation.id)
        return original_skip(ctx, generation)

    monkeypatch.setattr(queue_streams, "_library_skip", recording_skip)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_shuffle_data)
    _write_shuffle_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get(
        "/api/library/pool-queue", params={"shuffle": False, "start_generation_id": "g4"},
    )

    assert resp.status_code == 200
    assert scanned == ["g4"]
    assert [track["generation_id"] for track in resp.json()["takes"]] == ["g4"]
    assert resp.json()["skipped_complete"] is False


def test_library_pool_queue_unplayable_start_is_scanned_once_with_small_budget(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_audio_build(monkeypatch)
    import songmaker_cli.queue_streams as queue_streams

    monkeypatch.setattr(queue_streams, "LIBRARY_QUEUE_STREAM_SCAN_LIMIT", 1)
    monkeypatch.setattr(queue_streams, "QUEUE_STREAM_MAX_TRACKS", 5)
    original_skip = queue_streams._library_skip
    scanned: list[str] = []

    def recording_skip(ctx, generation):
        scanned.append(generation.id)
        return original_skip(ctx, generation)

    monkeypatch.setattr(queue_streams, "_library_skip", recording_skip)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_shuffle_data)
    _write_shuffle_audio_files(tmp_path)
    (tmp_path / "audio" / "user-a" / "g4.mp3").unlink()
    seed_session(client, "usera")

    resp = client.get(
        "/api/library/pool-queue", params={"shuffle": False, "start_generation_id": "g4"},
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == QUEUE_STREAM_UNPLAYABLE_START_DETAIL
    assert scanned == ["g4"]


def test_library_pool_queue_unknown_pool_is_422(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"pool": "favorites"})

    assert resp.status_code == 422


def test_generation_matches_pool_rules() -> None:
    picked = Generation(id="p", song_id="s", mp3_path="p.mp3", is_picked=True, is_kept=False)
    kept = Generation(id="k", song_id="s", mp3_path="k.mp3", is_picked=False, is_kept=True)
    both = Generation(id="b", song_id="s", mp3_path="b.mp3", is_picked=True, is_kept=True)
    plain = Generation(id="n", song_id="s", mp3_path="n.mp3", is_picked=False, is_kept=False)
    archived = Generation(
        id="a", song_id="s", mp3_path="a.mp3", is_picked=True, is_kept=True, is_archived=True
    )

    assert generation_matches_pool(picked, "mix") is True
    assert generation_matches_pool(kept, "mix") is True
    assert generation_matches_pool(both, "mix") is True
    assert generation_matches_pool(plain, "mix") is False
    assert generation_matches_pool(archived, "mix") is False
    assert generation_matches_pool(picked, "picks") is True
    assert generation_matches_pool(kept, "picks") is False
    assert generation_matches_pool(picked, "keeps") is False
    assert generation_matches_pool(kept, "keeps") is True
    assert generation_matches_pool(plain, "all") is True
    assert generation_matches_pool(archived, "all") is False


def test_collect_library_pool_dedupes_pick_and_keep_and_pins_out_of_pool_start() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    older = Generation(
        id="g-old",
        song_id="s1",
        mp3_path="old.mp3",
        is_picked=False,
        is_kept=False,
        created_at=t0,
    )
    both = Generation(
        id="g-both",
        song_id="s1",
        mp3_path="both.mp3",
        is_picked=True,
        is_kept=True,
        created_at=t0 + timedelta(days=2),
    )
    keep = Generation(
        id="g-keep",
        song_id="s1",
        mp3_path="keep.mp3",
        is_picked=False,
        is_kept=True,
        created_at=t0 + timedelta(days=1),
    )
    song = Song(id="s1", title="One", album_id="a1", track_number=1)
    song.generations = [older, both, keep]

    mixed = collect_library_pool_generations([song], "mix", older)
    assert [gen.id for gen in mixed] == ["g-old", "g-both", "g-keep"]

    mix_only = collect_library_pool_generations([song], "mix", None)
    assert [gen.id for gen in mix_only] == ["g-both", "g-keep"]


def _seed_library_pool_data(session) -> None:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    session.add(User(id="user-a", username="usera"))
    session.flush()
    session.add(Album(id="a1", title="Alpha", artist="A", created_by="user-a"))
    session.add(Album(id="a2", title="Beta", artist="A", created_by="user-a"))
    session.flush()
    session.add(
        Song(id="s1", title="One", album_id="a1", track_number=1, slug="one"),
    )
    session.add(
        Song(id="s2", title="Two", album_id="a1", track_number=2, slug="two"),
    )
    session.add(
        Song(id="s3", title="Three", album_id="a2", track_number=1, slug="three"),
    )
    session.flush()
    for index, song_id in enumerate(("s1", "s2", "s3"), start=1):
        session.add(Version(id=f"v{index}", song_id=song_id, version_number=1, lyrics=""))
    session.flush()
    session.add_all(
        [
            Generation(
                id="g-old",
                song_id="s1",
                version_id="v1",
                generation_number=1,
                mp3_path="user-a/g-old.mp3",
                seed=1,
                created_at=t0,
            ),
            Generation(
                id="g-pick",
                song_id="s1",
                version_id="v1",
                generation_number=2,
                mp3_path="user-a/g-pick.mp3",
                seed=2,
                is_picked=True,
                created_at=t0 + timedelta(days=1),
            ),
            Generation(
                id="g-keep-a",
                song_id="s1",
                version_id="v1",
                generation_number=3,
                mp3_path="user-a/g-keep-a.mp3",
                seed=3,
                is_kept=True,
                created_at=t0 + timedelta(days=2),
            ),
            Generation(
                id="g-both",
                song_id="s1",
                version_id="v1",
                generation_number=4,
                mp3_path="user-a/g-both.mp3",
                seed=4,
                is_picked=True,
                is_kept=True,
                created_at=t0 + timedelta(days=3),
            ),
            Generation(
                id="g-arch",
                song_id="s1",
                version_id="v1",
                generation_number=5,
                mp3_path="user-a/g-arch.mp3",
                seed=5,
                is_picked=True,
                is_kept=True,
                is_archived=True,
                created_at=t0 + timedelta(days=4),
            ),
            Generation(
                id="g-keep-b",
                song_id="s2",
                version_id="v2",
                generation_number=1,
                mp3_path="user-a/g-keep-b.mp3",
                seed=6,
                is_kept=True,
                created_at=t0 + timedelta(days=1),
            ),
            Generation(
                id="g-missing",
                song_id="s2",
                version_id="v2",
                generation_number=2,
                mp3_path="user-a/g-missing.mp3",
                seed=7,
                is_kept=True,
                created_at=t0 + timedelta(days=2),
            ),
            Generation(
                id="g-pick-b",
                song_id="s3",
                version_id="v3",
                generation_number=1,
                mp3_path="user-a/g-pick-b.mp3",
                seed=8,
                is_picked=True,
                created_at=t0,
            ),
        ]
    )


def _write_pool_audio_files(root: Path) -> None:
    path = root / "audio" / "user-a"
    path.mkdir(parents=True, exist_ok=True)
    for name in (
        "g-old.mp3",
        "g-pick.mp3",
        "g-keep-a.mp3",
        "g-both.mp3",
        "g-arch.mp3",
        "g-keep-b.mp3",
        "g-pick-b.mp3",
    ):
        (path / name).write_bytes(b"source")


@pytest.mark.parametrize(
    ("pool", "expected"),
    [
        ("mix", ["g-both", "g-keep-a", "g-pick", "g-keep-b", "g-pick-b"]),
        ("picks", ["g-both", "g-pick", "g-pick-b"]),
        ("keeps", ["g-both", "g-keep-a", "g-keep-b"]),
        ("all", ["g-both", "g-keep-a", "g-pick", "g-old", "g-keep-b", "g-pick-b"]),
    ],
)
def test_library_pool_queue_pool_sets(
    tmp_path: Path, monkeypatch, pool: str, expected: list[str]
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_pool_data)
    _write_pool_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"pool": pool})

    assert resp.status_code == 200
    assert [track["generation_id"] for track in resp.json()["takes"]] == expected


def test_library_pool_queue_default_pool_is_mix(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_pool_data)
    _write_pool_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={})

    assert resp.status_code == 200
    assert [track["generation_id"] for track in resp.json()["takes"]] == [
        "g-both",
        "g-keep-a",
        "g-pick",
        "g-keep-b",
        "g-pick-b",
    ]
    assert resp.json()["skipped"] == [
        {"song_id": "s2", "generation_id": "g-missing", "reason": "missing_file"}
    ]


def test_library_pool_queue_reports_every_unplayable_reason(tmp_path: Path, monkeypatch) -> None:
    def seed_with_unplayable(session) -> None:
        _seed_library_pool_data(session)
        session.add_all(
            [
                Generation(
                    id="g-no-path",
                    song_id="s2",
                    version_id="v2",
                    generation_number=3,
                    mp3_path="",
                    is_kept=True,
                ),
                Generation(
                    id="g-directory",
                    song_id="s3",
                    version_id="v3",
                    generation_number=2,
                    mp3_path="user-a/directory.mp3",
                    is_picked=True,
                ),
            ]
        )

    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=seed_with_unplayable)
    _write_pool_audio_files(tmp_path)
    (tmp_path / "audio" / "user-a" / "directory.mp3").mkdir()
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"pool": "all"})

    assert resp.status_code == 200
    assert resp.json()["skipped"] == [
        {"song_id": "s2", "generation_id": "g-no-path", "reason": "missing_path"},
        {"song_id": "s2", "generation_id": "g-missing", "reason": "missing_file"},
        {"song_id": "s3", "generation_id": "g-directory", "reason": "unreadable_file"},
    ]
    assert resp.json()["skipped_complete"] is True


def test_library_skip_classifies_missing_path(tmp_path: Path) -> None:
    generation = Generation(id="g-no-path", song_id="s2", mp3_path=None)
    ctx = type("Context", (), {"audio_dir": tmp_path / "audio"})()

    skip = _library_skip(ctx, generation)

    assert skip is not None
    assert skip.model_dump() == {
        "song_id": "s2",
        "generation_id": "g-no-path",
        "reason": "missing_path",
    }


def test_library_skip_rejects_fifo_before_open(tmp_path: Path, monkeypatch) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    fifo_path = audio_dir / "take.mp3"
    os.mkfifo(fifo_path)
    generation = Generation(id="g-fifo", song_id="s2", mp3_path="take.mp3")
    ctx = type("Context", (), {"audio_dir": audio_dir})()
    original_open = Path.open

    def guarded_open(path: Path, *args, **kwargs):
        if path == fifo_path:
            pytest.fail("FIFO must be rejected before open")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    skip = _library_skip(ctx, generation)

    assert skip is not None
    assert skip.reason == "unreadable_file"


@pytest.mark.parametrize("failure", ["open", "read", "probe"])
def test_library_skip_maps_file_failures_to_unreadable(
    tmp_path: Path, monkeypatch, failure: str
) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    audio_path = audio_dir / "take.mp3"
    audio_path.write_bytes(b"audio")
    generation = Generation(id="g-broken", song_id="s-broken", mp3_path="take.mp3")
    ctx = type("Context", (), {"audio_dir": audio_dir})()
    original_open = Path.open

    class FailingReader:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size: int):
            raise OSError("read failed")

    if failure == "open":

        def fail_open(path: Path, *args, **kwargs):
            if path == audio_path:
                raise PermissionError("open failed")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", fail_open)
    elif failure == "read":

        def fail_read(path: Path, *args, **kwargs):
            if path == audio_path:
                return FailingReader()
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", fail_read)
    else:

        def fail_probe(_path: Path) -> float:
            raise HTTPException(422, "probe failed")

        monkeypatch.setattr(
            "songmaker_cli.queue_streams.probe_audio_duration",
            fail_probe,
        )

    skip = _library_skip(ctx, generation)

    assert skip is not None
    assert skip.model_dump() == {
        "song_id": "s-broken",
        "generation_id": "g-broken",
        "reason": "unreadable_file",
    }


def test_library_pool_queue_out_of_pool_start_is_temporary(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_pool_data)
    _write_pool_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get(
        "/api/library/pool-queue", params={"pool": "mix", "start_generation_id": "g-old"},
    )

    assert resp.status_code == 200
    assert [track["generation_id"] for track in resp.json()["takes"]] == [
        "g-old",
        "g-both",
        "g-keep-a",
        "g-pick",
        "g-keep-b",
        "g-pick-b",
    ]


def test_library_pool_queue_matches_collect_without_ffmpeg(tmp_path: Path, monkeypatch) -> None:
    concat_calls: list[object] = []
    import songmaker_cli.queue_streams as qs

    monkeypatch.setattr(qs, "probe_audio_duration", lambda _path: 10.0)
    monkeypatch.setattr(
        qs,
        "run_ffmpeg_concat",
        lambda *_args, **_kwargs: concat_calls.append("concat"),
    )
    monkeypatch.setattr(
        qs,
        "build_queue_stream_snapshot",
        lambda *_args, **_kwargs: concat_calls.append("snapshot"),
    )
    client, factory = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"pool": "mix"})

    assert resp.status_code == 200
    assert concat_calls == []
    data = resp.json()
    assert data["pool"] == "mix"
    take_ids = [take["generation_id"] for take in data["takes"]]
    assert take_ids == ["g1b", "g2"]
    assert {take["song_id"] for take in data["takes"]} == {"s1", "s2"}
    assert all(take["mp3_path"] for take in data["takes"])

    from songmaker_cli.db.queries.songs import list_songs

    with factory() as session:
        songs = list_songs(session, user_id="user-a", light=False)
        songs = sorted(
            songs,
            key=lambda song: (
                song.album.title if song.album is not None else "",
                song.track_number,
                song.id,
            ),
        )
        collected = collect_library_pool_generations(songs, "mix", None)
    assert take_ids == [generation.id for generation in collected]


def test_library_pool_queue_foreign_start_generation_is_404(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    resp = client.get(
        "/api/library/pool-queue",
        params={"pool": "mix", "start_generation_id": "g5"},
    )

    assert resp.status_code == 404


def test_library_pool_queue_empty_pool_is_422(tmp_path: Path, monkeypatch) -> None:
    def seed_unplayable(session) -> None:
        _seed_library_data(session)
        from songmaker_cli.db.models import Generation

        for gen in session.query(Generation).filter(Generation.id.in_(["g1", "g1b", "g2"])):
            gen.is_archived = True
        session.flush()

    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=seed_unplayable)
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"pool": "mix"})

    assert resp.status_code == 422
    assert resp.json()["detail"] == "No playable takes in pool 'mix'"


def test_library_pool_queue_rate_limited(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    import songmaker_cli.constants as consts

    monkeypatch.setattr(consts, "QUEUE_STREAM_AUTH_RATE_LIMIT", 1)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    seed_session(client, "usera")

    first = client.get("/api/library/pool-queue", params={"pool": "mix"})
    second = client.get("/api/library/pool-queue", params={"pool": "mix"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["Retry-After"] == str(consts.QUEUE_STREAM_AUTH_RATE_WINDOW_SECONDS)


def test_library_pool_queue_rate_limiter_failure_is_503(
    tmp_path: Path, monkeypatch
) -> None:
    class BrokenLimiter:
        def is_allowed(self, _user_id, *, limit: int, window_seconds: int):
            raise RuntimeError("down")

    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    seed_session(client, "usera")
    monkeypatch.setattr(
        "songmaker_cli.queue_streams._get_queue_stream_limiter",
        lambda _request: BrokenLimiter(),
    )

    resp = client.get("/api/library/pool-queue", params={"pool": "mix"})

    assert resp.status_code == 503


@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize(
    ("method", "path", "schema_path"),
    [
        ("POST", "/api/queue-streams", "/api/queue-streams"),
        ("POST", "/api/queue-streams/library", "/api/queue-streams/library"),
        (
            "GET", "/api/queue-streams/opaque-snapshot/audio",
            "/api/queue-streams/{snapshot_id}/audio",
        ),
    ],
)
def test_removed_queue_stream_routes_are_unknown(
    tmp_path: Path, authenticated: bool, method: str, path: str, schema_path: str,
) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    if authenticated:
        seed_session(client, "owner")
    response = client.request(method, path)
    unknown = client.request(method, "/api/no-such-route")
    assert (response.status_code, response.json()) == (unknown.status_code, unknown.json())
    assert schema_path not in client.app.openapi()["paths"]
