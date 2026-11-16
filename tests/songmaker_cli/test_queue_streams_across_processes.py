"""Two web processes: a queue stream asked for at once is built once and both serve it."""

from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from redis import Redis
from support.owner_lease_epoch import settled_epoch
from support.web_cluster_world import WebProcess

from songmaker_cli.db.models import Album, Generation, Song, User, Version

ALBUM_SLUG = "open-windows"
OWNER_ID = "owner-of-open-windows"
TAKE_PATH = f"{OWNER_ID}/take.mp3"
SLOW_BUILD_SECONDS = 2
REQUEST_TIMEOUT_SECONDS = 30.0


def _slow_counting_ffmpeg(locked_ffmpeg: Path, builds: Path) -> Path:
    """An `ffmpeg` ahead of PATH that records each run, lingers, then runs the locked one."""
    directory = builds.parent / "slow-ffmpeg"
    directory.mkdir()
    script = directory / "ffmpeg"
    script.write_text(
        f"#!/bin/sh\necho run >> '{builds}'\nsleep {SLOW_BUILD_SECONDS}\n"
        f"exec '{locked_ffmpeg}' \"$@\"\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return directory


def _write_take(locked_ffmpeg: Path, audio_dir: Path) -> None:
    take = audio_dir / TAKE_PATH
    take.parent.mkdir(parents=True)
    subprocess.run(  # noqa: S603 - the locked ffmpeg with fixed arguments
        [str(locked_ffmpeg), "-v", "error", "-f", "lavfi", "-i", "sine=duration=2", str(take)],
        check=True,
    )


def _seed_shared_album(factory) -> None:
    with factory() as session:
        session.add(User(id=OWNER_ID, username="owner"))
        session.flush()
        session.add(Album(
            id="album-of-owner", title="Open Windows", artist="Pat",
            created_by=OWNER_ID, is_shared=True, share_slug=ALBUM_SLUG,
        ))
        session.flush()
        session.add(
            Song(id="song", title="One", album_id="album-of-owner", track_number=1, slug="one"),
        )
        session.flush()
        session.add(Version(id="version", song_id="song", version_number=1, lyrics="one"))
        session.flush()
        session.add(Generation(
            id="take", song_id="song", version_id="version", generation_number=1,
            mp3_path=TAKE_PATH, seed=1, is_picked=True,
        ))
        session.commit()


def _ask_for_the_stream(process: WebProcess) -> httpx.Response:
    return httpx.post(
        f"{process.url}/shared/{ALBUM_SLUG}/stream",
        headers={"Origin": process.url},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def test_a_queue_stream_asked_for_at_once_is_built_once_and_both_processes_serve_it(
    web_cluster, redis_url: str, locked_ffmpeg: Path, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster, factory = web_cluster
    Redis.from_url(redis_url).set(*settled_epoch())
    builds = tmp_path / "builds.txt"
    builds.touch()
    monkeypatch.setenv(
        "PATH", f"{_slow_counting_ffmpeg(locked_ffmpeg, builds)}{os.pathsep}{os.environ['PATH']}",
    )
    _write_take(locked_ffmpeg, cluster.audio_dir)
    _seed_shared_album(factory)
    process_a, process_b = cluster.start("a"), cluster.start("b")

    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(_ask_for_the_stream, (process_a, process_b)))
    builds_after_the_asks = len(builds.read_text(encoding="utf-8").splitlines())
    audio = [
        httpx.get(
            f"{process.url}{answer.json()['stream_url']}",
            headers={"Range": "bytes=0-3"}, timeout=REQUEST_TIMEOUT_SECONDS,
        )
        for process, answer in zip((process_a, process_b), answers, strict=True)
    ]

    assert (
        [answer.status_code for answer in answers],
        len({answer.json()["snapshot_id"] for answer in answers}),
        builds_after_the_asks,
        [response.status_code for response in audio],
    ) == ([200, 200], 1, 1, [206, 206])
