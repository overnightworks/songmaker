from __future__ import annotations

from pathlib import Path

import pytest
from support.web_app import make_test_app, seed_session, web_client

from songmaker_cli import audio_files, queue_streams
from songmaker_cli.db.models import Album, Generation, Song, User, Version


def _seed_takes(session, *, take_count: int) -> None:
    session.add(User(id="user-a", username="usera"))
    session.flush()
    session.add(Album(id="a1", title="Album", artist="A", created_by="user-a"))
    session.flush()
    for index in range(1, take_count + 1):
        session.add(
            Song(
                id=f"s{index}", title=f"Song {index}", album_id="a1",
                track_number=index, slug=f"song-{index}",
            ),
        )
    session.flush()
    for index in range(1, take_count + 1):
        session.add(Version(id=f"v{index}", song_id=f"s{index}", version_number=1, lyrics=""))
    session.flush()
    for index in range(1, take_count + 1):
        session.add(
            Generation(
                id=f"g{index}", song_id=f"s{index}", version_id=f"v{index}",
                generation_number=1, mp3_path=f"user-a/g{index}.mp3", seed=index,
                is_picked=True,
            ),
        )


def test_shared_album_stream_refuses_a_take_whose_duration_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory,
) -> None:
    monkeypatch.setattr(audio_files, "read_audio_duration", lambda _path: None)
    client, _ = make_test_app(
        tmp_path, factory=pg_factory, seed_db=lambda session: _seed_takes(session, take_count=1),
    )
    audio_dir = tmp_path / "audio" / "user-a"
    audio_dir.mkdir(parents=True)
    (audio_dir / "g1.mp3").write_bytes(b"source")
    seed_session(client, "usera")
    slug = client.post("/api/albums/a1/share").json()["share_slug"]

    response = web_client(client.app, cookies={}).post(f"/shared/{slug}/stream")

    assert response.status_code == 422
    assert response.json()["detail"] == "Could not read audio duration"


def test_library_pool_queue_names_the_scan_window_when_it_held_only_unplayable_takes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory,
) -> None:
    monkeypatch.setattr(queue_streams, "LIBRARY_QUEUE_STREAM_SCAN_LIMIT", 1)
    client, _ = make_test_app(
        tmp_path, factory=pg_factory, seed_db=lambda session: _seed_takes(session, take_count=2),
    )
    seed_session(client, "usera")

    response = client.get("/api/library/pool-queue")

    assert response.status_code == 422
    assert response.json()["detail"] == "No playable takes in scanned library window"
