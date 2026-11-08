"""The queue-stream cache: reuse of a built snapshot, the cleanup sweep and the size quota."""

from __future__ import annotations

import os
import time
from datetime import timedelta
from pathlib import Path

import pytest
from support.queue_stream_audio import stub_audio_build
from support.web_app import TEST_SECRET, make_fake_redis

from songmaker_cli import queue_streams
from songmaker_cli.app_context import AppContext
from songmaker_cli.db.models import Generation
from songmaker_cli.queue_streams import (
    QUEUE_STREAM_DIRNAME,
    QUEUE_STREAM_ORPHAN_MAX_AGE,
    QueueStreamManifest,
    build_queue_stream_snapshot,
    cleanup_expired_queue_streams,
    track_source_from_generation,
)

OTHER_SNAPSHOT_ID = "f" * 32
PAST_ORPHAN_AGE = QUEUE_STREAM_ORPHAN_MAX_AGE + timedelta(hours=1)


@pytest.fixture
def ctx(tmp_path: Path, pg_factory, monkeypatch) -> AppContext:
    stub_audio_build(monkeypatch)
    audio_dir = tmp_path / "audio"
    (audio_dir / "owner").mkdir(parents=True)
    (audio_dir / "owner" / "take.mp3").write_bytes(b"source")
    return AppContext(
        db=pg_factory, audio_dir=audio_dir, data_dir=tmp_path / "data",
        signing_key=TEST_SECRET, redis=make_fake_redis(),
    )


@pytest.fixture
def stream_dir(ctx: AppContext) -> Path:
    path = ctx.data_dir / QUEUE_STREAM_DIRNAME
    path.mkdir(parents=True)
    return path


def _build_snapshot(ctx: AppContext, scope_id: str = "album") -> str:
    take = Generation(
        id="take", mp3_path="owner/take.mp3", generation_number=1, model_mode="base",
    )
    source = track_source_from_generation(
        take, key="take", index=0, entry_id=None, audio_url="/audio/owner/take.mp3",
    )
    manifest = build_queue_stream_snapshot(
        ctx, [source], scope="shared-album", scope_id=scope_id, stream_url="",
    )
    return manifest.snapshot_id


def _set_age(path: Path, age: timedelta) -> None:
    moment = time.time() - age.total_seconds()
    os.utime(path, (moment, moment), follow_symlinks=False)


def _plant(stream_dir: Path, name: str, age: timedelta, size: int = 1) -> Path:
    path = stream_dir / name
    path.write_bytes(b"x" * size)
    _set_age(path, age)
    return path


def test_a_second_build_of_the_same_queue_reuses_the_first_snapshot(ctx, stream_dir) -> None:
    first = _build_snapshot(ctx)

    assert _build_snapshot(ctx) == first


def test_a_build_passes_over_a_snapshot_whose_audio_is_gone(ctx, stream_dir) -> None:
    first = _build_snapshot(ctx)
    (stream_dir / f"{first}.mp3").unlink()

    assert _build_snapshot(ctx) != first


def test_a_build_passes_over_an_expired_snapshot(ctx, stream_dir) -> None:
    first = _build_snapshot(ctx)
    manifest_path = stream_dir / f"{first}.json"
    manifest = QueueStreamManifest.load(manifest_path)
    expired = manifest.model_copy(update={"expires_at": manifest.expires_at - timedelta(days=1)})
    expired.save(manifest_path)

    assert _build_snapshot(ctx) != first


def test_a_build_passes_over_an_unreadable_manifest(ctx, stream_dir) -> None:
    first = _build_snapshot(ctx)
    (stream_dir / f"{first}.json").write_text("{", encoding="utf-8")

    assert _build_snapshot(ctx) != first


@pytest.mark.parametrize("file_stem", [OTHER_SNAPSHOT_ID, "notes"])
def test_a_build_passes_over_a_manifest_whose_name_is_not_the_id_it_records(
    ctx, stream_dir, file_stem
) -> None:
    first = _build_snapshot(ctx)
    (stream_dir / f"{first}.json").rename(stream_dir / f"{file_stem}.json")

    assert _build_snapshot(ctx) != first


def test_a_build_passes_over_a_manifest_recording_an_id_that_is_not_a_valid_snapshot_id(
    ctx, stream_dir
) -> None:
    first = _build_snapshot(ctx)
    manifest_path = stream_dir / f"{first}.json"
    manifest = QueueStreamManifest.load(manifest_path)
    manifest_path.unlink()
    manifest.model_copy(update={"snapshot_id": "notes"}).save(stream_dir / "notes.json")
    (stream_dir / f"{first}.mp3").rename(stream_dir / "notes.mp3")

    assert _build_snapshot(ctx) != "notes"


def test_the_sweep_keeps_every_file_of_a_live_snapshot_however_old(ctx, stream_dir) -> None:
    live = _build_snapshot(ctx)
    audio = stream_dir / f"{live}.mp3"
    _set_age(audio, PAST_ORPHAN_AGE)

    cleanup_expired_queue_streams(ctx)

    assert audio.exists()


def test_the_sweep_removes_the_files_of_an_expired_snapshot(ctx, stream_dir) -> None:
    first = _build_snapshot(ctx)
    manifest_path = stream_dir / f"{first}.json"
    manifest = QueueStreamManifest.load(manifest_path)
    manifest.model_copy(update={"expires_at": manifest.expires_at - timedelta(days=1)}).save(
        manifest_path
    )

    cleanup_expired_queue_streams(ctx)

    assert sorted(stream_dir.iterdir()) == []


@pytest.mark.parametrize(
    "name",
    ["stray.mp3", "notes.txt", f"{OTHER_SNAPSHOT_ID}.tmp.mp3", f"{OTHER_SNAPSHOT_ID}.concat.txt"],
)
def test_the_sweep_removes_a_leftover_older_than_a_day_whether_or_not_it_names_a_snapshot(
    ctx, stream_dir, name
) -> None:
    leftover = _plant(stream_dir, name, PAST_ORPHAN_AGE)

    cleanup_expired_queue_streams(ctx)

    assert not leftover.exists()


@pytest.mark.parametrize("name", ["stray.mp3", f"{OTHER_SNAPSHOT_ID}.tmp.mp3"])
def test_the_sweep_keeps_a_leftover_younger_than_a_day(ctx, stream_dir, name) -> None:
    leftover = _plant(stream_dir, name, timedelta(hours=1))

    cleanup_expired_queue_streams(ctx)

    assert leftover.exists()


def test_the_sweep_keeps_a_subdirectory_however_old(ctx, stream_dir) -> None:
    folder = stream_dir / "folder"
    folder.mkdir()
    _set_age(folder, PAST_ORPHAN_AGE)

    cleanup_expired_queue_streams(ctx)

    assert folder.is_dir()


def test_the_sweep_skips_a_file_it_cannot_stat(ctx, stream_dir) -> None:
    dangling = stream_dir / "dangling.mp3"
    dangling.symlink_to(stream_dir / "missing")

    cleanup_expired_queue_streams(ctx)

    assert dangling.is_symlink()


def test_an_over_quota_sweep_leaves_a_young_temporary_audio_of_a_running_build(
    ctx, stream_dir, monkeypatch
) -> None:
    monkeypatch.setattr(queue_streams, "QUEUE_STREAM_MAX_CACHE_BYTES", 10)
    running = _plant(stream_dir, f"{OTHER_SNAPSHOT_ID}.tmp.mp3", timedelta(minutes=5), size=100)

    cleanup_expired_queue_streams(ctx)

    assert running.exists()


def test_eviction_neither_counts_nor_removes_a_stray_mp3(ctx, stream_dir, monkeypatch) -> None:
    monkeypatch.setattr(queue_streams, "QUEUE_STREAM_MAX_CACHE_BYTES", 10)
    stray = _plant(stream_dir, "stray.mp3", timedelta(hours=1), size=100)

    cleanup_expired_queue_streams(ctx)

    assert stray.exists()


def test_eviction_skips_a_snapshot_audio_it_cannot_stat(ctx, stream_dir, monkeypatch) -> None:
    monkeypatch.setattr(queue_streams, "QUEUE_STREAM_MAX_CACHE_BYTES", 1)
    dangling = stream_dir / f"{OTHER_SNAPSHOT_ID}.mp3"
    dangling.symlink_to(stream_dir / "missing")

    cleanup_expired_queue_streams(ctx)

    assert dangling.is_symlink()


def test_eviction_removes_the_oldest_snapshot_first_and_stops_once_the_cache_fits(
    ctx, stream_dir, monkeypatch
) -> None:
    oldest = _build_snapshot(ctx, "oldest")
    middle = _build_snapshot(ctx, "middle")
    newest = _build_snapshot(ctx, "newest")
    for index, snapshot_id in enumerate((oldest, middle, newest)):
        _set_age(stream_dir / f"{snapshot_id}.mp3", timedelta(hours=3 - index))
    one_snapshot = (stream_dir / f"{newest}.mp3").stat().st_size
    monkeypatch.setattr(queue_streams, "QUEUE_STREAM_MAX_CACHE_BYTES", 2 * one_snapshot)

    cleanup_expired_queue_streams(ctx)

    assert {path.name for path in stream_dir.iterdir()} == {
        f"{middle}.mp3", f"{middle}.json", f"{newest}.mp3", f"{newest}.json",
    }


def test_a_build_over_quota_evicts_older_snapshots_and_keeps_its_own(
    ctx, stream_dir, monkeypatch
) -> None:
    older = _build_snapshot(ctx, "older")
    monkeypatch.setattr(queue_streams, "QUEUE_STREAM_MAX_CACHE_BYTES", 1)

    newer = _build_snapshot(ctx, "newer")

    assert {path.name for path in stream_dir.iterdir()} == {f"{newer}.mp3", f"{newer}.json"}
    assert older != newer


def test_the_sweep_before_any_snapshot_exists_creates_nothing(ctx) -> None:
    cleanup_expired_queue_streams(ctx)

    assert not (ctx.data_dir / QUEUE_STREAM_DIRNAME).exists()
