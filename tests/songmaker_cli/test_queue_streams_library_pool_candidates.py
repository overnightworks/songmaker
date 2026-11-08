"""Library pool candidates: their order and the ones whose audio is unavailable."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from support.queue_stream_audio import stub_audio_build
from support.web_app import make_test_app, seed_session

from songmaker_cli.db.models import Album, Generation, Song, User, Version
from songmaker_cli.queue_streams import _library_skip


def _seed_library_ordering_ties(session) -> None:
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    session.add(User(id="user-a", username="usera"))
    session.flush()
    session.add(Album(id="album-z", title="Alpha", artist="A", created_by="user-a"))
    session.add(Album(id="album-a", title="Zulu", artist="A", created_by="user-a"))
    session.flush()
    for song_id, album_id in (
        ("song-b", "album-z"),
        ("song-a", "album-z"),
        ("song-c", "album-a"),
    ):
        session.add(
            Song(id=song_id, title=song_id, album_id=album_id, track_number=1, slug=song_id)
        )
    session.flush()
    for song_id in ("song-b", "song-a", "song-c"):
        session.add(Version(id=f"v-{song_id}", song_id=song_id, version_number=1, lyrics=""))
    session.flush()
    take_times = (
        ("song-a", "take-b", moment + timedelta(days=2)),
        ("song-a", "take-a", moment + timedelta(days=2)),
        ("song-a", "take-old", moment),
        ("song-a", "take-mid", moment + timedelta(days=1)),
        ("song-b", "take-only-b", moment),
        ("song-c", "take-only-c", moment),
    )
    for number, (song_id, take_id, created_at) in enumerate(take_times, start=1):
        session.add(
            Generation(
                id=take_id,
                song_id=song_id,
                version_id=f"v-{song_id}",
                generation_number=number,
                mp3_path=f"user-a/{take_id}.mp3",
                seed=number,
                is_picked=True,
                created_at=created_at,
            )
        )


def test_library_pool_queue_orders_ties_by_album_title_then_stable_identifiers(
    tmp_path: Path, monkeypatch, pg_factory
) -> None:
    """Spec: REQ-LISTENING-01 -- album title outranks album id, tied tracks fall back to the song
    id and tied takes to the take id, and a song's takes still run newest to oldest.
    """
    stub_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, factory=pg_factory, seed_db=_seed_library_ordering_ties)
    audio_path = tmp_path / "audio" / "user-a"
    audio_path.mkdir(parents=True)
    for take_id in (
        "take-a",
        "take-b",
        "take-old",
        "take-mid",
        "take-only-b",
        "take-only-c",
    ):
        (audio_path / f"{take_id}.mp3").write_bytes(b"source")
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"pool": "all"})

    assert resp.status_code == 200
    assert [track["generation_id"] for track in resp.json()["takes"]] == [
        "take-a",
        "take-b",
        "take-mid",
        "take-old",
        "take-only-b",
        "take-only-c",
    ]


def _seed_unavailable_pick(session) -> None:
    session.add(User(id="user-a", username="usera"))
    session.flush()
    session.add(Album(id="a1", title="Alpha", artist="A", created_by="user-a"))
    session.flush()
    for track_number, song_id in enumerate(("s1", "s2"), start=1):
        session.add(
            Song(id=song_id, title=song_id, album_id="a1", track_number=track_number, slug=song_id)
        )
        session.flush()
        session.add(Version(id=f"v-{song_id}", song_id=song_id, version_number=1, lyrics=""))
    session.flush()
    take_rows = (
        ("g-pick-ok", "s1", True),
        ("g-pick-gone", "s2", True),
        ("g-spare", "s2", False),
    )
    for number, (take_id, song_id, picked) in enumerate(take_rows, start=1):
        session.add(
            Generation(
                id=take_id,
                song_id=song_id,
                version_id=f"v-{song_id}",
                generation_number=number,
                mp3_path=f"user-a/{take_id}.mp3",
                is_picked=picked,
            )
        )


def test_library_pool_queue_never_replaces_an_unavailable_pick_with_another_take(
    tmp_path: Path, monkeypatch, pg_factory
) -> None:
    """Spec: REQ-LISTENING-06 -- a Pick whose audio file is missing is reported and its song
    contributes no other take, although another take of that song is playable.
    """
    stub_audio_build(monkeypatch)
    client, _ = make_test_app(tmp_path, factory=pg_factory, seed_db=_seed_unavailable_pick)
    audio_path = tmp_path / "audio" / "user-a"
    audio_path.mkdir(parents=True)
    for take_id in ("g-pick-ok", "g-spare"):
        (audio_path / f"{take_id}.mp3").write_bytes(b"source")
    seed_session(client, "usera")

    resp = client.get("/api/library/pool-queue", params={"pool": "picks"})

    assert resp.status_code == 200
    assert resp.json()["skipped"] == [
        {"song_id": "s2", "generation_id": "g-pick-gone", "reason": "missing_file"}
    ]
    assert [track["generation_id"] for track in resp.json()["takes"]] == ["g-pick-ok"]


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
