"""The queue-stream cache: reuse of a built snapshot, the cleanup sweep and the size quota."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import anyio
import pytest
from anyio.from_thread import BlockingPortal, start_blocking_portal
from support.object_store import AgedObjectStore, an_aged_object_store
from support.queue_stream_audio import stub_audio_build
from support.web_app import SettledFakeAsyncRedis, make_app_context, make_fake_redis

from songmaker_cli import queue_streams
from songmaker_cli.app_context import AppContext
from songmaker_cli.db.models import Generation
from songmaker_cli.queue_streams import (
    QUEUE_STREAM_ORPHAN_MAX_AGE,
    build_queue_stream_snapshot,
    cleanup_expired_queue_streams,
    queue_stream_audio_object_key,
    queue_stream_manifest_object_key,
    track_source_from_generation,
)

OTHER_SNAPSHOT_ID = "f" * 32
PAST_ORPHAN_AGE = QUEUE_STREAM_ORPHAN_MAX_AGE + timedelta(hours=1)


_request_loop: BlockingPortal | None = None


@pytest.fixture(autouse=True)
def _event_loop_of_the_requests():
    """The loop a request's worker thread reaches the build lock on; one per test."""
    global _request_loop
    with start_blocking_portal() as portal:
        _request_loop = portal
        yield
    _request_loop = None


def _in_a_request_thread(function):
    assert _request_loop is not None
    return _request_loop.call(anyio.to_thread.run_sync, function)


@pytest.fixture
def ctx(tmp_path: Path, pg_factory, monkeypatch) -> AppContext:
    stub_audio_build(monkeypatch)
    audio_dir = tmp_path / "audio"
    (audio_dir / "owner").mkdir(parents=True)
    (audio_dir / "owner" / "take.mp3").write_bytes(b"source")
    return make_app_context(
        object_store=an_aged_object_store(),
        db=pg_factory,
        audio_dir=audio_dir,
        data_dir=tmp_path / "data",
        redis=make_fake_redis(),
        async_redis=SettledFakeAsyncRedis(),
    )


def _aged_store(ctx: AppContext) -> AgedObjectStore:
    assert isinstance(ctx.object_store, AgedObjectStore)
    return ctx.object_store


def _keys(ctx: AppContext) -> set[str]:
    return {entry.key for entry in ctx.object_store.list(queue_streams.QUEUE_STREAM_KEY_PREFIX)}


def _snapshot_keys(snapshot_id: str) -> set[str]:
    return {
        queue_stream_audio_object_key(snapshot_id),
        queue_stream_manifest_object_key(snapshot_id),
    }


def _plant(ctx: AppContext, name: str, age: timedelta, size: int = 1) -> str:
    key = f"{queue_streams.QUEUE_STREAM_KEY_PREFIX}{name}"
    ctx.object_store.put_bytes(key, b"x" * size, content_type="application/octet-stream")
    _aged_store(ctx).age(key, age)
    return key


def _expire(ctx: AppContext, snapshot_id: str) -> None:
    key = queue_stream_manifest_object_key(snapshot_id)
    manifest = queue_streams.QueueStreamManifest.model_validate_json(
        ctx.object_store.get_bytes(key),
    )
    expired = manifest.model_copy(update={"expires_at": manifest.expires_at - timedelta(days=1)})
    ctx.object_store.put_bytes(
        key, expired.model_dump_json().encode(), content_type="application/json",
    )


def _build_snapshot(ctx: AppContext, scope_id: str = "album") -> str:
    take = Generation(
        id="take", mp3_path="owner/take.mp3", generation_number=1, model_mode="base",
    )
    source = track_source_from_generation(
        take, key="take", index=0, entry_id=None, audio_url="/audio/owner/take.mp3",
    )
    manifest = _in_a_request_thread(lambda: build_queue_stream_snapshot(
        ctx, [source], scope="shared-album", scope_id=scope_id, stream_url="",
    ))
    return manifest.snapshot_id


def test_a_second_build_of_the_same_queue_reuses_the_first_snapshot(ctx) -> None:
    first = _build_snapshot(ctx)

    assert _build_snapshot(ctx) == first


def test_a_build_holds_no_pooled_database_connection_while_ffmpeg_runs(
    ctx, pg_factory, monkeypatch
) -> None:
    pool = pg_factory.kw["bind"].pool
    connections_out_during_ffmpeg: list[int] = []
    original_concat = queue_streams.run_ffmpeg_concat

    def watching_concat(concat_path: Path, output_path: Path) -> None:
        connections_out_during_ffmpeg.append(pool.checkedout())
        original_concat(concat_path, output_path)

    monkeypatch.setattr(queue_streams, "run_ffmpeg_concat", watching_concat)

    _build_snapshot(ctx)

    assert connections_out_during_ffmpeg == [0]


def test_a_build_leaves_nothing_of_its_rendering_on_the_machine(
    ctx, monkeypatch, tmp_path: Path
) -> None:
    work_dirs: list[Path] = []
    original_concat = queue_streams.run_ffmpeg_concat

    def noting_concat(concat_path: Path, output_path: Path) -> None:
        work_dirs.append(output_path.parent)
        original_concat(concat_path, output_path)

    monkeypatch.setattr(queue_streams, "run_ffmpeg_concat", noting_concat)

    snapshot_id = _build_snapshot(ctx)

    assert (
        [path.exists() for path in work_dirs], (tmp_path / "data").exists(), _keys(ctx),
    ) == ([False], False, _snapshot_keys(snapshot_id))


def test_a_build_passes_over_an_expired_snapshot(ctx) -> None:
    first = _build_snapshot(ctx)
    _expire(ctx, first)

    assert _build_snapshot(ctx) != first


def test_a_build_passes_over_an_unreadable_record(ctx) -> None:
    first = _build_snapshot(ctx)
    ctx.object_store.put_bytes(
        queue_stream_manifest_object_key(first), b"{", content_type="application/json",
    )

    assert _build_snapshot(ctx) != first


def test_the_sweep_keeps_every_object_of_a_live_snapshot_however_old(ctx) -> None:
    live = _build_snapshot(ctx)
    for key in _snapshot_keys(live):
        _aged_store(ctx).age(key, PAST_ORPHAN_AGE)

    cleanup_expired_queue_streams(ctx)

    assert _keys(ctx) == _snapshot_keys(live)


def test_the_sweep_removes_the_objects_of_an_expired_snapshot(ctx) -> None:
    first = _build_snapshot(ctx)
    _expire(ctx, first)

    cleanup_expired_queue_streams(ctx)

    assert _keys(ctx) == set()


def test_the_sweep_removes_the_objects_of_a_snapshot_whose_record_is_unreadable(ctx) -> None:
    first = _build_snapshot(ctx)
    ctx.object_store.put_bytes(
        queue_stream_manifest_object_key(first), b"{", content_type="application/json",
    )

    cleanup_expired_queue_streams(ctx)

    assert _keys(ctx) == set()


@pytest.mark.parametrize(
    "name",
    ["stray.mp3", "notes.txt", f"{OTHER_SNAPSHOT_ID}.mp3", f"{OTHER_SNAPSHOT_ID}.json"],
)
def test_the_sweep_removes_an_object_older_than_a_day_whether_or_not_it_names_a_snapshot(
    ctx, name
) -> None:
    leftover = _plant(ctx, name, PAST_ORPHAN_AGE)

    cleanup_expired_queue_streams(ctx)

    assert leftover not in _keys(ctx)


@pytest.mark.parametrize("name", ["stray.mp3", f"{OTHER_SNAPSHOT_ID}.mp3"])
def test_the_sweep_keeps_an_object_younger_than_a_day(ctx, name) -> None:
    leftover = _plant(ctx, name, timedelta(hours=1))

    cleanup_expired_queue_streams(ctx)

    assert leftover in _keys(ctx)


def test_eviction_neither_counts_nor_removes_a_stray_mp3(ctx, monkeypatch) -> None:
    monkeypatch.setattr(queue_streams, "QUEUE_STREAM_MAX_CACHE_BYTES", 10)
    stray = _plant(ctx, "stray.mp3", timedelta(hours=1), size=100)

    cleanup_expired_queue_streams(ctx)

    assert stray in _keys(ctx)


def test_eviction_removes_the_oldest_snapshot_first_and_stops_once_the_cache_fits(
    ctx, monkeypatch
) -> None:
    oldest = _build_snapshot(ctx, "oldest")
    middle = _build_snapshot(ctx, "middle")
    newest = _build_snapshot(ctx, "newest")
    for index, snapshot_id in enumerate((oldest, middle, newest)):
        _aged_store(ctx).age(queue_stream_audio_object_key(snapshot_id), timedelta(hours=3 - index))
    one_snapshot = next(
        entry.size for entry in ctx.object_store.list(queue_streams.QUEUE_STREAM_KEY_PREFIX)
        if entry.key == queue_stream_audio_object_key(newest)
    )
    monkeypatch.setattr(queue_streams, "QUEUE_STREAM_MAX_CACHE_BYTES", 2 * one_snapshot)

    cleanup_expired_queue_streams(ctx)

    assert _keys(ctx) == _snapshot_keys(middle) | _snapshot_keys(newest)


def test_a_build_over_quota_evicts_older_snapshots_and_keeps_its_own(ctx, monkeypatch) -> None:
    older = _build_snapshot(ctx, "older")
    monkeypatch.setattr(queue_streams, "QUEUE_STREAM_MAX_CACHE_BYTES", 1)

    newer = _build_snapshot(ctx, "newer")

    assert _keys(ctx) == _snapshot_keys(newer)
    assert older != newer
