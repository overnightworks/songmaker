"""Tests for cached queue stream snapshots."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import login_and_csrf, make_test_app
from fastapi.testclient import TestClient

from songmaker_cli.auth import hash_password
from songmaker_cli.db.models import Album, Generation, Playlist, PlaylistEntry, Song, User, Version
from songmaker_cli.queue_stream_api import (
    collect_library_pool_generations,
    generation_matches_pool,
    shuffle_library_sources,
)
from songmaker_cli.queue_streams import QueueStreamSource


def _seed_queue_data(session) -> None:
    owner = User(id="owner-id", username="owner", password_hash=hash_password("pass1234"))
    other = User(id="other-id", username="other", password_hash=hash_password("pass1234"))
    session.add_all([owner, other])
    session.flush()
    session.add(Album(id="a1", title="Album", artist="Artist", created_by=owner.id))
    session.add(Album(id="a2", title="Other", artist="Other", created_by=other.id))
    session.flush()
    session.add(Song(id="s1", title="One", album_id="a1", track_number=1))
    session.add(Song(id="s2", title="Two", album_id="a1", track_number=2))
    session.add(Song(id="s3", title="Other", album_id="a2", track_number=1))
    session.flush()
    session.add(Version(id="v1", song_id="s1", version_number=1, lyrics="one"))
    session.add(Version(id="v2", song_id="s2", version_number=1, lyrics="two"))
    session.add(Version(id="v3", song_id="s3", version_number=1, lyrics="other"))
    session.flush()
    session.add(Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="owner-id/g1.mp3", seed=1, is_picked=True,
    ))
    session.add(Generation(
        id="g2", song_id="s2", version_id="v2", generation_number=1,
        mp3_path="owner-id/g2.mp3", seed=2, is_picked=True,
    ))
    session.add(Generation(
        id="g3", song_id="s3", version_id="v3", generation_number=1,
        mp3_path="other-id/g3.mp3", seed=3, is_picked=True,
    ))
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


def test_authenticated_queue_stream_snapshot_and_audio_range(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    resp = client.post(
        "/api/queue-streams",
        json={
            "tracks": [
                {"generation_id": "g1", "entry_id": "pe1"},
                {"generation_id": "g1", "entry_id": "pe2"},
            ]
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_duration"] == 20
    assert [t["key"] for t in data["tracks"]] == ["pe1", "pe2"]
    assert data["tracks"][1]["start_offset"] == 10

    audio = client.get(data["stream_url"], headers={"Range": "bytes=0-3"})
    assert audio.status_code == 206
    assert audio.headers["Accept-Ranges"] == "bytes"
    assert audio.content == b"\xff\xfb\x90\x00"


def test_authenticated_queue_stream_rejects_inaccessible_generation(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    resp = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g3"}]})

    assert resp.status_code == 404


def test_authenticated_queue_stream_rate_limited(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    import songmaker_cli.constants as consts
    import songmaker_cli.queue_stream_api as queue_stream_api

    monkeypatch.setattr(consts, "QUEUE_STREAM_AUTH_RATE_LIMIT", 1)
    monkeypatch.setattr(queue_stream_api._consts, "QUEUE_STREAM_AUTH_RATE_LIMIT", 1)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    first = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g1"}]})
    second = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g1"}]})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["Retry-After"] == str(consts.QUEUE_STREAM_AUTH_RATE_WINDOW_SECONDS)


def test_shared_playlist_queue_stream_snapshot_and_audio(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")
    share = client.post("/api/playlists/pl1/share")
    slug = share.json()["share_slug"]
    public = TestClient(client.app, cookies={})

    get_resp = public.get(f"/shared/playlist/{slug}/stream")
    assert get_resp.status_code == 405

    resp = public.post(f"/shared/playlist/{slug}/stream")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tracks"]) == 2
    assert [track["entry_id"] for track in data["tracks"]] == ["pe1", "pe2"]
    assert data["tracks"][0]["audio_url"].startswith(f"/shared/playlist/{slug}/audio/")
    second = public.post(f"/shared/playlist/{slug}/stream")
    assert second.status_code == 200
    assert second.json()["snapshot_id"] == data["snapshot_id"]
    audio = public.get(data["stream_url"], headers={"Range": "bytes=0-3"})
    assert audio.status_code == 206


def test_shared_playlist_queue_stream_revalidates_entries(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")
    share = client.post("/api/playlists/pl1/share")
    slug = share.json()["share_slug"]
    public = TestClient(client.app, cookies={})

    resp = public.post(f"/shared/playlist/{slug}/stream")
    assert resp.status_code == 200
    data = resp.json()

    remove = client.delete("/api/playlists/pl1/entries/pe1")
    assert remove.status_code == 200

    audio = public.get(data["stream_url"], headers={"Range": "bytes=0-3"})

    assert audio.status_code == 404


def test_queue_stream_cache_quota_keeps_new_snapshot(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    import songmaker_cli.queue_streams as qs

    monkeypatch.setattr(qs, "QUEUE_STREAM_MAX_CACHE_BYTES", 1)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    resp = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g1"}]})

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
    login_and_csrf(client, "owner", "pass1234")

    resp = client.post(
        "/api/queue-streams",
        json={"tracks": [{"generation_id": "g1"}, {"generation_id": "g2"}]},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["windowed"] is True
    assert len(data["tracks"]) == 1
    assert data["tracks"][0]["generation_id"] == "g1"


def test_queue_stream_request_model_rejects_more_than_500_tracks(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    # 501 tracks must be rejected by model validation before any handler logic runs
    resp_over = client.post(
        "/api/queue-streams",
        json={"tracks": [{"generation_id": "g1"}] * 501},
    )
    assert resp_over.status_code == 422

    # 500 tracks passes model validation; windowed by count (MAX_TRACKS=200) and succeeds
    import songmaker_cli.queue_streams as qs

    monkeypatch.setattr(qs, "QUEUE_STREAM_MAX_TRACKS", 1)
    resp_at_limit = client.post(
        "/api/queue-streams",
        json={"tracks": [{"generation_id": "g1"}] * 500},
    )
    assert resp_at_limit.status_code == 200
    assert resp_at_limit.json()["windowed"] is True


def test_queue_stream_windowed_by_duration(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    import songmaker_cli.queue_streams as qs

    # duration=10s per track; cap at 15s admits only the first track
    monkeypatch.setattr(qs, "QUEUE_STREAM_MAX_DURATION_SECONDS", 15)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    resp = client.post(
        "/api/queue-streams",
        json={"tracks": [{"generation_id": "g1"}, {"generation_id": "g2"}]},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["windowed"] is True
    assert len(data["tracks"]) == 1
    assert data["tracks"][0]["generation_id"] == "g1"


def test_queue_stream_not_windowed_when_within_limits(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    resp = client.post(
        "/api/queue-streams",
        json={"tracks": [{"generation_id": "g1"}, {"generation_id": "g2"}]},
    )

    assert resp.status_code == 200
    assert resp.json()["windowed"] is False


def test_legacy_manifest_without_windowed_field_loads_as_unwindowed(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    first = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g1"}]})
    assert first.status_code == 200
    snapshot_id = first.json()["snapshot_id"]

    manifest_path = tmp_path / "data" / "queue-streams" / f"{snapshot_id}.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("windowed", None)
    manifest_path.write_text(json.dumps(manifest))

    second = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g1"}]})
    assert second.status_code == 200
    assert second.json()["windowed"] is False


def test_queue_stream_first_track_too_long_raises_422(tmp_path: Path, monkeypatch) -> None:
    import songmaker_cli.queue_streams as qs

    _patch_audio_build(monkeypatch)
    # first (and only) track duration exceeds the cap → empty window → 422
    monkeypatch.setattr(qs, "QUEUE_STREAM_MAX_DURATION_SECONDS", 5)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    resp = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g1"}]})

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
    user_a = User(id="user-a", username="usera", password_hash=hash_password("pass1234"))
    user_b = User(id="user-b", username="userb", password_hash=hash_password("pass1234"))
    session.add_all([user_a, user_b])
    session.flush()

    session.add(Album(id="a1", title="First", artist="A", created_by="user-a"))
    session.add(Album(id="a2", title="Second", artist="A", created_by="user-a"))
    session.add(Album(id="a3", title="B Album", artist="B", created_by="user-b"))
    session.flush()

    session.add(Song(id="s1", title="One", album_id="a1", track_number=1))
    session.add(Song(id="s2", title="Two", album_id="a1", track_number=2))
    session.add(Song(id="s3", title="Three", album_id="a2", track_number=1))
    session.add(Song(id="s4", title="Four", album_id="a2", track_number=2))
    session.add(Song(id="s5", title="Five", album_id="a3", track_number=1))
    session.flush()

    session.add(Version(id="v1", song_id="s1", version_number=1, lyrics=""))
    session.add(Version(id="v2", song_id="s2", version_number=1, lyrics=""))
    session.add(Version(id="v3", song_id="s3", version_number=1, lyrics=""))
    session.add(Version(id="v5", song_id="s5", version_number=1, lyrics=""))
    session.flush()

    # s1: non-picked gen first (by created_at desc: g1b > g1), g1b is picked
    session.add(Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="user-a/g1.mp3", seed=1, is_picked=False,
    ))
    session.add(Generation(
        id="g1b", song_id="s1", version_id="v1", generation_number=2,
        mp3_path="user-a/g1b.mp3", seed=2, is_picked=True,
    ))
    # s2: kept, not picked — mix includes it; picks does not
    session.add(Generation(
        id="g2", song_id="s2", version_id="v2", generation_number=1,
        mp3_path="user-a/g2.mp3", seed=3, is_picked=False, is_kept=True,
    ))
    # s3: single archived gen → song has no eligible generation
    session.add(Generation(
        id="g3", song_id="s3", version_id="v3", generation_number=1,
        mp3_path="user-a/g3.mp3", seed=4, is_picked=False, is_archived=True,
    ))
    # s4: no generations at all
    # s5 (user B)
    session.add(Generation(
        id="g5", song_id="s5", version_id="v5", generation_number=1,
        mp3_path="user-b/g5.mp3", seed=5, is_picked=True,
    ))


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


def test_library_stream_order_and_tracks(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    login_and_csrf(client, "usera", "pass1234")

    resp = client.post("/api/queue-streams/library", json={})

    assert resp.status_code == 200
    data = resp.json()
    # s3 (archived gen) and s4 (no gens) are skipped → only s1 and s2 appear
    assert [t["generation_id"] for t in data["tracks"]] == ["g1b", "g2"]
    # album a1 comes before a2; within a1, track 1 before track 2
    assert data["tracks"][0]["song_id"] == "s1"
    assert data["tracks"][1]["song_id"] == "s2"
    # indices are contiguous from 0
    assert [t["index"] for t in data["tracks"]] == [0, 1]
    assert data["tracks"][1]["start_offset"] == pytest.approx(10.0)


def test_library_stream_picks_picked_over_first(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    login_and_csrf(client, "usera", "pass1234")

    resp = client.post("/api/queue-streams/library", json={})

    assert resp.status_code == 200
    # s1 has both g1 (not picked) and g1b (picked); library must choose g1b
    s1_track = next(t for t in resp.json()["tracks"] if t["song_id"] == "s1")
    assert s1_track["generation_id"] == "g1b"


def test_library_stream_excludes_archived_generations(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    login_and_csrf(client, "usera", "pass1234")

    resp = client.post("/api/queue-streams/library", json={})

    assert resp.status_code == 200
    song_ids = [t["song_id"] for t in resp.json()["tracks"]]
    assert "s3" not in song_ids  # s3's only gen is archived


def test_library_stream_skips_songs_without_playable_generations(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    login_and_csrf(client, "usera", "pass1234")

    resp = client.post("/api/queue-streams/library", json={})

    assert resp.status_code == 200
    song_ids = [t["song_id"] for t in resp.json()["tracks"]]
    assert "s4" not in song_ids  # s4 has no generations at all


def test_library_stream_rotation_via_start_generation_id(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    login_and_csrf(client, "usera", "pass1234")

    resp = client.post("/api/queue-streams/library", json={"start_generation_id": "g2"})

    assert resp.status_code == 200
    data = resp.json()
    # Rotation puts g2's song first; g1b's song wraps to the end
    assert [t["generation_id"] for t in data["tracks"]] == ["g2", "g1b"]
    assert [t["index"] for t in data["tracks"]] == [0, 1]


def test_library_stream_start_take_is_the_clicked_generation(
    tmp_path: Path, monkeypatch
) -> None:
    """Clicking a non-picked take streams that take, not the song's pick."""
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    login_and_csrf(client, "usera", "pass1234")

    resp = client.post("/api/queue-streams/library", json={"start_generation_id": "g1"})

    assert resp.status_code == 200
    tracks = resp.json()["tracks"]
    assert tracks[0]["song_id"] == "s1"
    assert tracks[0]["generation_id"] == "g1"
    assert [t["generation_id"] for t in tracks] == ["g1", "g1b", "g2"]


def test_library_stream_start_generation_id_not_found_starts_from_beginning(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    login_and_csrf(client, "usera", "pass1234")

    resp = client.post(
        "/api/queue-streams/library", json={"start_generation_id": "nonexistent-id"},
    )

    assert resp.status_code == 200
    # No rotation: library order unchanged
    assert [t["generation_id"] for t in resp.json()["tracks"]] == ["g1b", "g2"]


def test_library_stream_windowed_for_oversize_library(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    import songmaker_cli.queue_streams as qs

    monkeypatch.setattr(qs, "QUEUE_STREAM_MAX_TRACKS", 1)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    login_and_csrf(client, "usera", "pass1234")

    resp = client.post("/api/queue-streams/library", json={})

    assert resp.status_code == 200
    data = resp.json()
    assert data["windowed"] is True
    assert len(data["tracks"]) == 1


def test_library_stream_empty_playable_library_is_422(tmp_path: Path, monkeypatch) -> None:
    """Songs with only archived or missing generations make an honest 422, not an empty stream."""

    def seed_unplayable(session) -> None:
        _seed_library_data(session)
        from songmaker_cli.db.models import Generation

        for gen in session.query(Generation).filter(Generation.id.in_(["g1", "g1b", "g2"])):
            gen.is_archived = True
        session.flush()

    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=seed_unplayable)
    login_and_csrf(client, "usera", "pass1234")

    resp = client.post("/api/queue-streams/library", json={})

    assert resp.status_code == 422


def test_library_stream_cross_user_isolation(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    login_and_csrf(client, "usera", "pass1234")

    resp_a = client.post("/api/queue-streams/library", json={})
    assert resp_a.status_code == 200
    stream_url_a = resp_a.json()["stream_url"]
    gen_ids_a = {t["generation_id"] for t in resp_a.json()["tracks"]}
    # User A's library contains only their own generations
    assert gen_ids_a == {"g1b", "g2"}

    client_b = TestClient(client.app, cookies={})
    login_and_csrf(client_b, "userb", "pass1234")

    resp_b = client_b.post("/api/queue-streams/library", json={})
    assert resp_b.status_code == 200
    gen_ids_b = {t["generation_id"] for t in resp_b.json()["tracks"]}
    # User B's library contains only their own generation
    assert gen_ids_b == {"g5"}
    assert gen_ids_a.isdisjoint(gen_ids_b)

    # User B cannot access user A's stream audio
    audio_resp = client_b.get(stream_url_a, headers={"Range": "bytes=0-3"})
    assert audio_resp.status_code == 404


def test_expired_queue_stream_snapshot_is_rejected(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")
    resp = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g1"}]})
    data = resp.json()
    manifest_path = tmp_path / "data" / "queue-streams" / f"{data['snapshot_id']}.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    manifest_path.write_text(json.dumps(manifest))

    audio = client.get(data["stream_url"])

    assert audio.status_code == 404


# ── Pinning tests ───────────────────────────────────────────────────────────


def test_pinned_snapshot_survives_ttl_on_access(tmp_path: Path, monkeypatch) -> None:
    """An expired snapshot that is actively pinned must not be reaped on access."""
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    resp = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g1"}]})
    assert resp.status_code == 200
    snapshot_id = resp.json()["snapshot_id"]
    manifest_path = tmp_path / "data" / "queue-streams" / f"{snapshot_id}.json"

    manifest = json.loads(manifest_path.read_text())
    manifest["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    manifest["pinned"] = True
    manifest["pinned_at"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest))

    audio = client.get(f"/api/queue-streams/{snapshot_id}/audio", headers={"Range": "bytes=0-3"})

    assert audio.status_code == 206


def test_pinned_snapshot_survives_cleanup_sweep(tmp_path: Path, monkeypatch) -> None:
    """An expired but actively pinned snapshot must not be deleted by the cleanup sweep."""
    from songmaker_cli.queue_streams import cleanup_expired_queue_streams

    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    resp = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g1"}]})
    assert resp.status_code == 200
    snapshot_id = resp.json()["snapshot_id"]
    stream_dir = tmp_path / "data" / "queue-streams"
    manifest_path = stream_dir / f"{snapshot_id}.json"

    manifest = json.loads(manifest_path.read_text())
    manifest["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    manifest["pinned"] = True
    manifest["pinned_at"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest))

    cleanup_expired_queue_streams(client.app.state.ctx)

    assert manifest_path.exists()
    assert (stream_dir / f"{snapshot_id}.mp3").exists()


def test_abandoned_pin_is_reaped_by_cleanup_sweep(tmp_path: Path, monkeypatch) -> None:
    """A pinned snapshot whose pin_at is older than PIN_MAX_AGE must be reaped."""
    from songmaker_cli.queue_streams import cleanup_expired_queue_streams

    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    resp = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g1"}]})
    assert resp.status_code == 200
    snapshot_id = resp.json()["snapshot_id"]
    stream_dir = tmp_path / "data" / "queue-streams"
    manifest_path = stream_dir / f"{snapshot_id}.json"

    manifest = json.loads(manifest_path.read_text())
    manifest["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    manifest["pinned"] = True
    manifest["pinned_at"] = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    manifest_path.write_text(json.dumps(manifest))

    cleanup_expired_queue_streams(client.app.state.ctx)

    assert not manifest_path.exists()
    assert not (stream_dir / f"{snapshot_id}.mp3").exists()


def test_pinned_snapshot_excluded_from_quota_eviction(tmp_path: Path, monkeypatch) -> None:
    """Quota eviction must evict an unpinned snapshot rather than a pinned one."""
    _patch_audio_build(monkeypatch)
    import songmaker_cli.queue_streams as qs

    monkeypatch.setattr(qs, "QUEUE_STREAM_MAX_CACHE_BYTES", 1)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    # Build snapshot A and pin it via direct manifest edit
    resp_a = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g1"}]})
    assert resp_a.status_code == 200
    snapshot_a = resp_a.json()["snapshot_id"]
    manifest_path_a = tmp_path / "data" / "queue-streams" / f"{snapshot_a}.json"
    manifest_a = json.loads(manifest_path_a.read_text())
    manifest_a["pinned"] = True
    manifest_a["pinned_at"] = datetime.now(timezone.utc).isoformat()
    manifest_path_a.write_text(json.dumps(manifest_a))

    # Build snapshot B (unpinned) — cleanup runs before each build
    resp_b = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g2"}]})
    assert resp_b.status_code == 200
    snapshot_b = resp_b.json()["snapshot_id"]

    # Build snapshot C with different content — quota enforcement must evict B not A
    resp_c = client.post(
        "/api/queue-streams",
        json={"tracks": [{"generation_id": "g1"}, {"generation_id": "g2"}]},
    )
    assert resp_c.status_code == 200
    snapshot_c = resp_c.json()["snapshot_id"]

    stream_dir = tmp_path / "data" / "queue-streams"
    assert (stream_dir / f"{snapshot_a}.mp3").exists(), "Pinned snapshot must not be evicted"
    assert (stream_dir / f"{snapshot_c}.mp3").exists(), "Just-built snapshot must survive"
    assert not (stream_dir / f"{snapshot_b}.mp3").exists(), "Unpinned snapshot should be evicted"


def test_pin_snapshot_refused_when_pinned_bytes_cap_exceeded(
    tmp_path: Path, monkeypatch
) -> None:
    """PIN must be refused with 409 when the pinned-bytes cap would be exceeded."""
    _patch_audio_build(monkeypatch)
    import songmaker_cli.queue_streams as qs

    monkeypatch.setattr(qs, "QUEUE_STREAM_PINNED_MAX_BYTES", 0)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    resp = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g1"}]})
    assert resp.status_code == 200
    snapshot_id = resp.json()["snapshot_id"]

    pin_resp = client.post(f"/api/queue-streams/{snapshot_id}/pin")

    assert pin_resp.status_code == 409


def test_pin_unpin_round_trip_via_endpoints(tmp_path: Path, monkeypatch) -> None:
    """POST .../pin sets pinned=True; DELETE .../pin clears it back to False."""
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    resp = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g1"}]})
    assert resp.status_code == 200
    snapshot_id = resp.json()["snapshot_id"]

    pin_resp = client.post(f"/api/queue-streams/{snapshot_id}/pin")
    assert pin_resp.status_code == 200
    pin_data = pin_resp.json()
    assert pin_data["snapshot_id"] == snapshot_id
    assert pin_data["pinned"] is True
    assert pin_data["pinned_at"] is not None

    unpin_resp = client.delete(f"/api/queue-streams/{snapshot_id}/pin")
    assert unpin_resp.status_code == 200
    unpin_data = unpin_resp.json()
    assert unpin_data["snapshot_id"] == snapshot_id
    assert unpin_data["pinned"] is False
    assert unpin_data["pinned_at"] is None


def test_user_cannot_pin_another_users_snapshot(tmp_path: Path, monkeypatch) -> None:
    """A user must not be able to pin a snapshot that belongs to another user."""
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    resp = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g1"}]})
    assert resp.status_code == 200
    snapshot_id = resp.json()["snapshot_id"]

    client_other = TestClient(client.app, cookies={})
    login_and_csrf(client_other, "other", "pass1234")

    pin_resp = client_other.post(f"/api/queue-streams/{snapshot_id}/pin")

    assert pin_resp.status_code == 404


def test_shared_scope_snapshot_pin_returns_404(tmp_path: Path, monkeypatch) -> None:
    """Pinning a shared-scope snapshot must return 404, not 403."""
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")
    share = client.post("/api/playlists/pl1/share")
    slug = share.json()["share_slug"]
    public = TestClient(client.app, cookies={})

    stream_resp = public.post(f"/shared/playlist/{slug}/stream")
    assert stream_resp.status_code == 200
    snapshot_id = stream_resp.json()["snapshot_id"]

    pin_resp = client.post(f"/api/queue-streams/{snapshot_id}/pin")
    assert pin_resp.status_code == 404


def test_crashed_json_tmp_file_cleaned_up_as_orphan(tmp_path: Path, monkeypatch) -> None:
    """A leftover .json.tmp file from a crashed _atomic_write_manifest must be
    recognised as belonging to its (orphaned) snapshot and removed by the sweep.

    The real scenario: _atomic_write_manifest crashed before the rename, so the
    .json manifest was never written. The snapshot_id is therefore not live and
    the .json.tmp file is a plain orphan.
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


def test_legacy_manifest_without_pin_fields_is_accessible(tmp_path: Path, monkeypatch) -> None:
    """A pre-pin manifest (no pinned/pinned_at fields) is read as unpinned."""
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_queue_data)
    _write_audio_files(tmp_path)
    login_and_csrf(client, "owner", "pass1234")

    resp = client.post("/api/queue-streams", json={"tracks": [{"generation_id": "g1"}]})
    assert resp.status_code == 200
    snapshot_id = resp.json()["snapshot_id"]
    manifest_path = tmp_path / "data" / "queue-streams" / f"{snapshot_id}.json"

    # Simulate a legacy manifest by removing the pin fields
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("pinned", None)
    manifest.pop("pinned_at", None)
    manifest_path.write_text(json.dumps(manifest))

    audio = client.get(f"/api/queue-streams/{snapshot_id}/audio", headers={"Range": "bytes=0-3"})
    assert audio.status_code == 206

    unpin_resp = client.delete(f"/api/queue-streams/{snapshot_id}/pin")
    assert unpin_resp.status_code == 200
    assert unpin_resp.json()["pinned"] is False
    assert unpin_resp.json()["pinned_at"] is None


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
    session.add(User(id="user-a", username="usera", password_hash=hash_password("pass1234")))
    session.flush()
    session.add(Album(id="a1", title="Album", artist="A", created_by="user-a"))
    session.flush()
    for index in range(1, 5):
        session.add(Song(id=f"s{index}", title=f"Song {index}", album_id="a1", track_number=index))
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


def test_library_stream_without_shuffle_keeps_album_track_order(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_shuffle_data)
    _write_shuffle_audio_files(tmp_path)
    login_and_csrf(client, "usera", "pass1234")

    resp = client.post("/api/queue-streams/library", json={"shuffle": False})

    assert resp.status_code == 200
    assert [track["generation_id"] for track in resp.json()["tracks"]] == [
        "g1",
        "g2",
        "g3",
        "g4",
    ]


def test_library_stream_shuffle_uses_injected_rng(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_audio_build(monkeypatch)
    monkeypatch.setattr(
        "songmaker_cli.queue_stream_api.random.shuffle", _reverse_in_place
    )
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_shuffle_data)
    _write_shuffle_audio_files(tmp_path)
    login_and_csrf(client, "usera", "pass1234")

    resp = client.post(
        "/api/queue-streams/library",
        json={"shuffle": True, "start_generation_id": "g2"},
    )

    assert resp.status_code == 200
    assert [track["generation_id"] for track in resp.json()["tracks"]] == [
        "g2",
        "g4",
        "g3",
        "g1",
    ]
    assert [track["index"] for track in resp.json()["tracks"]] == [0, 1, 2, 3]


def test_library_stream_unknown_pool_is_422(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_data)
    _write_library_audio_files(tmp_path)
    login_and_csrf(client, "usera", "pass1234")

    resp = client.post("/api/queue-streams/library", json={"pool": "favorites"})

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

    mixed = collect_library_pool_generations([song], "mix", older, lambda _gen: True)
    assert [gen.id for gen in mixed] == ["g-old", "g-both", "g-keep"]

    mix_only = collect_library_pool_generations([song], "mix", None, lambda _gen: True)
    assert [gen.id for gen in mix_only] == ["g-both", "g-keep"]


def _seed_library_pool_data(session) -> None:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    session.add(User(id="user-a", username="usera", password_hash=hash_password("pass1234")))
    session.flush()
    session.add(Album(id="a1", title="Alpha", artist="A", created_by="user-a"))
    session.add(Album(id="a2", title="Beta", artist="A", created_by="user-a"))
    session.flush()
    session.add(Song(id="s1", title="One", album_id="a1", track_number=1))
    session.add(Song(id="s2", title="Two", album_id="a1", track_number=2))
    session.add(Song(id="s3", title="Three", album_id="a2", track_number=1))
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
def test_library_stream_pool_sets(
    tmp_path: Path, monkeypatch, pool: str, expected: list[str]
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_pool_data)
    _write_pool_audio_files(tmp_path)
    login_and_csrf(client, "usera", "pass1234")

    resp = client.post("/api/queue-streams/library", json={"pool": pool})

    assert resp.status_code == 200
    assert [track["generation_id"] for track in resp.json()["tracks"]] == expected


def test_library_stream_default_pool_is_mix(tmp_path: Path, monkeypatch) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_pool_data)
    _write_pool_audio_files(tmp_path)
    login_and_csrf(client, "usera", "pass1234")

    resp = client.post("/api/queue-streams/library", json={})

    assert resp.status_code == 200
    assert [track["generation_id"] for track in resp.json()["tracks"]] == [
        "g-both",
        "g-keep-a",
        "g-pick",
        "g-keep-b",
        "g-pick-b",
    ]


def test_library_stream_out_of_pool_start_is_temporary(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_pool_data)
    _write_pool_audio_files(tmp_path)
    login_and_csrf(client, "usera", "pass1234")

    resp = client.post(
        "/api/queue-streams/library",
        json={"pool": "mix", "start_generation_id": "g-old"},
    )

    assert resp.status_code == 200
    assert [track["generation_id"] for track in resp.json()["tracks"]] == [
        "g-old",
        "g-both",
        "g-keep-a",
        "g-pick",
        "g-keep-b",
        "g-pick-b",
    ]
