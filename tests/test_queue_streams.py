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
        s2: gen g2 (not picked, non-archived)
            → library picks g2 (only eligible)
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
    # s2: single non-picked, non-archived gen
    session.add(Generation(
        id="g2", song_id="s2", version_id="v2", generation_number=1,
        mp3_path="user-a/g2.mp3", seed=3, is_picked=False,
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
