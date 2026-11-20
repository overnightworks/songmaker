"""Tests for ACE-Step Redis state helpers (web container side)."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import fakeredis.aioredis
import pytest
from support.owner_lease_epoch import settled_epoch
from support.refused_download import attempt_download_that_must_not_run
from support.wrapper_deps import settled_fake_redis

from acestep_worker.heartbeat import release_gpu_hold, renew_gpu_hold, reserve_gpu_hold
from songmaker_cli.acestep_state import (
    DOWNLOAD_KEY_PREFIX,
    DOWNLOAD_LOCK_LASTS,
    LM_FAILURE_KEY_PREFIX,
    QUEUE_KEY_PREFIX,
    WORKER_KEY_PREFIX,
    DownloadAlreadyRunning,
    DownloadLockLost,
    admit_generation,
    decr_queue_depth,
    download_key,
    download_locks,
    gpu_hold_is_free,
    gpu_hold_locks,
    lm_failure_key,
    queue_depth_key,
    read_download_in_progress,
    read_queue_depth,
    read_worker_state,
    single_flight_download,
    worker_is_online,
    worker_state_key,
)


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def server():
    return fakeredis.FakeServer()


@pytest.fixture
def redis(server):
    return fakeredis.aioredis.FakeRedis(server=server)


@pytest.fixture
def settled_redis(redis, event_loop):
    """A Redis that has run longer than any lock lasts, as a process finds it in operation."""
    event_loop.run_until_complete(redis.set(*settled_epoch()))
    return redis


@pytest.fixture
def another_process(server):
    """A second process's client on the same server."""
    return fakeredis.aioredis.FakeRedis(server=server)


def test_key_prefixes_match_worker_heartbeat(redis) -> None:
    from acestep_worker.heartbeat import (
        QUEUE_KEY_PREFIX as WORKER_QUEUE_PREFIX,
    )
    from acestep_worker.heartbeat import (
        WORKER_KEY_PREFIX as WORKER_WORKER_PREFIX,
    )
    from acestep_worker.heartbeat import gpu_hold_locks as worker_gpu_hold_locks

    assert WORKER_KEY_PREFIX == WORKER_WORKER_PREFIX
    assert QUEUE_KEY_PREFIX == WORKER_QUEUE_PREFIX
    assert gpu_hold_locks(redis).keys == worker_gpu_hold_locks(redis).keys
    assert gpu_hold_locks(redis).lasts == worker_gpu_hold_locks(redis).lasts


def test_lm_failure_key_matches_the_workers_key() -> None:
    from acestep_worker.lm_failure import LM_FAILURE_KEY_PREFIX as WORKER_PREFIX
    from acestep_worker.lm_failure import lm_failure_key as worker_lm_failure_key

    assert LM_FAILURE_KEY_PREFIX == WORKER_PREFIX
    assert lm_failure_key("acestep-worker-0") == worker_lm_failure_key("acestep-worker-0")


def test_heartbeat_payload_keys_match_admin_reader() -> None:
    from pathlib import Path
    from unittest.mock import MagicMock

    from acestep_worker.model_cache import ModelCache
    from acestep_worker.wrapper import WorkerDeps, build_state_payload
    from songmaker_cli.admin_api import _state_from_dict
    from songmaker_cli.api_models.workers import LoadedModelDetail  # noqa: F401

    async def fake_loader(_: str):
        from acestep_worker.model_cache import LoadedModel

        return LoadedModel(mode="sft", handle=None, port=8101)

    async def fake_unloader(_) -> None:
        return None

    cache = ModelCache(
        vram_budget_gb=24.0,
        model_sizes={"sft": 6.0},
        loader=fake_loader,
        unloader=fake_unloader,
    )
    asyncio.run(cache.load("sft"))
    asyncio.run(cache.pin("sft"))

    deps = WorkerDeps(
        worker_id="acestep-worker-0",
        cache=cache,
        task_store=MagicMock(),
        heartbeat=MagicMock(),
        redis=settled_fake_redis(),
        registry_client=None,
        registration=None,
        checkpoint_dir=Path("/nonexistent"),
        audio_output_dir=Path("/nonexistent"),
        internal_token="test-internal-token",
        generate_runner=MagicMock(),
    )
    payload = asyncio.run(build_state_payload(deps))

    state = _state_from_dict(payload, queue_depth=0)
    assert state is not None
    assert len(state.loaded) == 1, (
        f"writer/reader key mismatch: payload has keys {sorted(payload.keys())}, "
        f"reader expects 'loaded' as list[LoadedModelDetail]"
    )
    assert state.loaded[0].mode == "sft"
    assert state.loaded[0].size_gb == 6.0
    assert state.vram_used_gb == 6.0
    assert state.target_loading is None
    assert state.vram_total_gb == 24.0
    assert state.vram_measured is False
    assert state.available_modes == []
    assert state.pinned == ["sft"]
    assert state.loading_started_at is None


@pytest.mark.parametrize(
    ("payload_vram_measured", "expected"),
    [
        pytest.param({"loaded": [], "vram_measured": True}, True, id="measured"),
        pytest.param({"loaded": [], "vram_measured": False}, False, id="estimated"),
        pytest.param({"loaded": []}, None, id="legacy-payload-missing-field"),
    ],
)
def test_state_from_dict_reads_vram_measured(
    payload_vram_measured: dict, expected: bool | None
) -> None:
    from songmaker_cli.admin_api import _state_from_dict

    state = _state_from_dict(payload_vram_measured, queue_depth=0)

    assert state is not None
    assert state.vram_measured is expected


@pytest.mark.parametrize("has_error", [False, True])
def test_last_error_reader_preserves_pair(redis, event_loop, has_error: bool) -> None:
    """S15-04: Last error reader preserves pair."""
    from songmaker_cli.admin_api import _state_from_dict

    payload = {"loaded": [], "gpu_healthy": True}
    if has_error:
        payload.update(
            last_error="Worker failure\nunchanged", last_error_at="2026-10-18T10:00:00+00:00",
        )
    event_loop.run_until_complete(redis.set(worker_state_key("w1"), json.dumps(payload)))
    state = _state_from_dict(event_loop.run_until_complete(read_worker_state(redis, "w1")))
    assert state.last_error == payload.get("last_error")
    assert state.last_error_at == payload.get("last_error_at")


def test_worker_state_key_format() -> None:
    assert worker_state_key("acestep-worker-0") == "songmaker:acestep:worker:acestep-worker-0"


def test_queue_depth_key_format() -> None:
    assert queue_depth_key("acestep-worker-0") == "songmaker:acestep:queue:acestep-worker-0"


def test_reserve_wins_against_a_later_generation_admit(settled_redis, event_loop) -> None:
    assert event_loop.run_until_complete(reserve_gpu_hold(settled_redis, "w1"))

    assert not event_loop.run_until_complete(admit_generation(settled_redis, "w1"))
    assert event_loop.run_until_complete(read_queue_depth(settled_redis, "w1")) == 0


def test_generation_admit_wins_against_a_later_hold_reserve(settled_redis, event_loop) -> None:
    assert event_loop.run_until_complete(admit_generation(settled_redis, "w1"))

    assert not event_loop.run_until_complete(reserve_gpu_hold(settled_redis, "w1"))
    assert event_loop.run_until_complete(read_queue_depth(settled_redis, "w1")) == 1


class _AdmittingAfterADepthRead(fakeredis.aioredis.FakeRedis):
    """A client that runs an admission right after its ``after_read``-th read of the queue depth."""

    def __init__(self, *, server, worker_id: str, after_read: int, admit) -> None:
        super().__init__(server=server)
        self._depth_key = queue_depth_key(worker_id)
        self._after_read = after_read
        self._admit = admit
        self._depth_reads = 0

    async def get(self, name, *args, **kwargs):
        value = await super().get(name, *args, **kwargs)
        if name == self._depth_key:
            self._depth_reads += 1
            if self._depth_reads == self._after_read:
                await self._admit(self)
        return value


def test_a_reserve_that_finds_a_generation_admitted_in_between_releases_its_hold(
    settled_redis, server, event_loop,
) -> None:
    """The admission read the lock free, then the reserve took it: the depth read after
    ``acquire`` shows the admission, so the reserve gives the hold back."""
    reserving = _AdmittingAfterADepthRead(
        server=server, worker_id="w1", after_read=1,
        admit=lambda client: client.incr(queue_depth_key("w1")),
    )

    async def scenario() -> tuple[str | None, bool]:
        generation = await reserve_gpu_hold(reserving, "w1")
        return generation, await gpu_hold_is_free(settled_redis, "w1")

    assert event_loop.run_until_complete(scenario()) == (None, True)
    assert event_loop.run_until_complete(read_queue_depth(settled_redis, "w1")) == 1


def test_the_generation_controls_renew_and_release(settled_redis, event_loop) -> None:
    generation = event_loop.run_until_complete(reserve_gpu_hold(settled_redis, "w1"))
    assert generation
    assert not event_loop.run_until_complete(renew_gpu_hold(settled_redis, "w1", "wrong"))
    assert not event_loop.run_until_complete(release_gpu_hold(settled_redis, "w1", "wrong"))
    assert event_loop.run_until_complete(renew_gpu_hold(settled_redis, "w1", generation))
    assert event_loop.run_until_complete(release_gpu_hold(settled_redis, "w1", generation))
    assert event_loop.run_until_complete(admit_generation(settled_redis, "w1"))


def test_a_hold_is_free_only_while_none_is_live(settled_redis, event_loop) -> None:
    assert event_loop.run_until_complete(gpu_hold_is_free(settled_redis, "w1"))
    generation = event_loop.run_until_complete(reserve_gpu_hold(settled_redis, "w1"))
    assert not event_loop.run_until_complete(gpu_hold_is_free(settled_redis, "w1"))
    event_loop.run_until_complete(release_gpu_hold(settled_redis, "w1", generation))
    assert event_loop.run_until_complete(gpu_hold_is_free(settled_redis, "w1"))


def test_a_live_hold_keeps_every_reader_off_the_worker(settled_redis, event_loop) -> None:
    async def scenario() -> tuple[bool, bool, int]:
        assert await reserve_gpu_hold(settled_redis, "w1")
        free = await gpu_hold_is_free(settled_redis, "w1")
        admitted = await admit_generation(settled_redis, "w1")
        return free, admitted, await read_queue_depth(settled_redis, "w1")

    assert event_loop.run_until_complete(scenario()) == (False, False, 0)


def test_a_hold_and_an_admission_wait_out_a_redis_restart_without_failing(
    settled_redis, event_loop,
) -> None:
    """After a restart the hold may have been lost: nothing is admitted or reserved until a
    span passed, and every refusal is the ordinary busy answer."""

    async def scenario() -> tuple[bool, bool, str | None, int]:
        await settled_redis.flushall()
        free = await gpu_hold_is_free(settled_redis, "w1")
        admitted = await admit_generation(settled_redis, "w1")
        reserved = await reserve_gpu_hold(settled_redis, "w1")
        return free, admitted, reserved, await read_queue_depth(settled_redis, "w1")

    assert event_loop.run_until_complete(scenario()) == (False, False, None, 0)

    event_loop.run_until_complete(settled_redis.set(*settled_epoch()))

    assert event_loop.run_until_complete(admit_generation(settled_redis, "w1"))


def test_read_worker_state_missing(redis, event_loop) -> None:
    result = event_loop.run_until_complete(read_worker_state(redis, "missing"))
    assert result is None


def test_read_worker_state_present(redis, event_loop) -> None:
    payload = {
        "loaded": [{"mode": "xl-sft", "size_gb": 0}],
        "target_loading": None,
        "vram_used_gb": 12.4,
    }
    event_loop.run_until_complete(
        redis.set(worker_state_key("w1"), json.dumps(payload)),
    )
    result = event_loop.run_until_complete(read_worker_state(redis, "w1"))
    assert result == payload


# ── worker_is_online ─────────────────────────────────────────────


def test_worker_is_online_false_when_no_heartbeat() -> None:
    assert worker_is_online(None) is False


def test_worker_is_online_true_when_gpu_healthy() -> None:
    assert worker_is_online({"loaded": [], "gpu_healthy": True}) is True


def test_held_worker_remains_online() -> None:
    from songmaker_cli.admin_api import _derive_worker_status, _state_from_dict

    state = _state_from_dict(
        {"loaded": [], "gpu_healthy": True, "training_hold_seconds": 12},
        queue_depth=0,
    )

    assert _derive_worker_status(state) == "online"


def test_worker_is_online_false_when_gpu_unhealthy() -> None:
    """Issue #367: a worker whose GPU has gone away keeps heartbeating fine
    — its heartbeat existing is not enough, gpu_healthy must say True."""
    assert worker_is_online({"loaded": [], "gpu_healthy": False}) is False


def test_worker_is_online_false_when_gpu_healthy_field_missing() -> None:
    """Fail-closed (issue #367 revision): a heartbeat with no gpu_healthy
    key at all — an old or broken worker build that never learned to
    publish it — must never be silently assumed fine."""
    assert worker_is_online({"loaded": []}) is False


def test_read_queue_depth_missing_returns_zero(redis, event_loop) -> None:
    assert event_loop.run_until_complete(read_queue_depth(redis, "w1")) == 0


def test_decr_queue_depth(redis, event_loop) -> None:
    event_loop.run_until_complete(redis.set(queue_depth_key("w1"), 2))
    assert event_loop.run_until_complete(read_queue_depth(redis, "w1")) == 2
    assert event_loop.run_until_complete(decr_queue_depth(redis, "w1")) == 1
    assert event_loop.run_until_complete(read_queue_depth(redis, "w1")) == 1


def test_decode_handles_str_branch() -> None:
    from songmaker_cli.acestep_state import decode_redis_text

    assert decode_redis_text(None) is None
    assert decode_redis_text(b"abc") == "abc"
    assert decode_redis_text("xyz") == "xyz"


def test_download_key_format() -> None:
    assert download_key("xl-base") == "songmaker:acestep:download:xl-base"
    assert DOWNLOAD_KEY_PREFIX == "songmaker:acestep:download"


def test_read_download_in_progress_missing(redis, event_loop) -> None:
    assert event_loop.run_until_complete(read_download_in_progress(redis, "sft")) is None


def test_a_download_is_labelled_with_its_job_while_it_holds_the_lock(
    settled_redis, event_loop,
) -> None:
    async def scenario() -> tuple[str | None, int, str | None]:
        async with single_flight_download(settled_redis, "turbo", "job-x"):
            during = await read_download_in_progress(settled_redis, "turbo")
            label_seconds = await settled_redis.ttl(download_key("turbo"))
        return during, label_seconds, await read_download_in_progress(settled_redis, "turbo")

    during, label_seconds, after = event_loop.run_until_complete(scenario())

    assert (during, after) == ("job-x", None)
    assert 0 < label_seconds <= DOWNLOAD_LOCK_LASTS.total_seconds()


def test_a_second_download_of_a_mode_is_refused_with_the_holders_job(
    settled_redis, another_process, event_loop,
) -> None:
    async def scenario() -> str | None:
        async with single_flight_download(settled_redis, "sft", "job-1"):
            with pytest.raises(DownloadAlreadyRunning) as refused:
                await attempt_download_that_must_not_run(another_process, "sft", "job-2")
        return refused.value.job_id

    assert event_loop.run_until_complete(scenario()) == "job-1"


def test_two_modes_download_side_by_side(settled_redis, another_process, event_loop) -> None:
    async def scenario() -> None:
        async with single_flight_download(settled_redis, "sft", "job-1"):
            async with single_flight_download(another_process, "turbo", "job-2"):
                pass

    event_loop.run_until_complete(scenario())


def test_a_mode_downloads_again_once_its_download_ended(
    settled_redis, another_process, event_loop,
) -> None:
    async def scenario() -> None:
        async with single_flight_download(settled_redis, "sft", "job-1"):
            pass
        async with single_flight_download(another_process, "sft", "job-2"):
            pass

    event_loop.run_until_complete(scenario())


def test_a_download_waits_out_a_redis_restart_instead_of_failing(
    settled_redis, event_loop, monkeypatch,
) -> None:
    real_sleep = asyncio.sleep
    waits = 0

    async def settle_while_waiting(_seconds: float) -> None:
        nonlocal waits
        waits += 1
        await settled_redis.set(*settled_epoch())
        await real_sleep(0)

    async def scenario() -> str | None:
        await settled_redis.flushall()
        monkeypatch.setattr("songmaker_cli.acestep_state.asyncio.sleep", settle_while_waiting)
        async with single_flight_download(settled_redis, "sft", "job-1"):
            return await read_download_in_progress(settled_redis, "sft")

    assert event_loop.run_until_complete(scenario()) == "job-1"
    assert waits >= 1


def test_a_download_whose_lock_was_taken_over_stops_and_leaves_the_new_holders_label(
    settled_redis, another_process, event_loop, monkeypatch,
) -> None:
    monkeypatch.setattr(
        "songmaker_cli.acestep_state.DOWNLOAD_LOCK_EXTEND_EVERY", timedelta(milliseconds=10),
    )

    async def download_while_another_process_takes_the_lock() -> None:
        new_holder_locks = download_locks(another_process)
        async with single_flight_download(settled_redis, "sft", "job-1"):
            await another_process.zrem(new_holder_locks.keys.expiry, "sft")
            assert await new_holder_locks.acquire("sft") is not None
            await another_process.set(download_key("sft"), "job-2", ex=15)
            await asyncio.sleep(30)

    async def scenario() -> str | None:
        with pytest.raises(DownloadLockLost) as lost:
            await download_while_another_process_takes_the_lock()
        assert lost.value.mode == "sft"
        return await read_download_in_progress(another_process, "sft")

    assert event_loop.run_until_complete(scenario()) == "job-2"


def test_a_download_whose_first_stop_is_swallowed_by_its_block_is_stopped_again(
    settled_redis, another_process, event_loop, monkeypatch,
) -> None:
    """A native cancel racing a cancel scope of the block (anyio's connect) is absorbed by it."""
    monkeypatch.setattr(
        "songmaker_cli.acestep_state.DOWNLOAD_LOCK_EXTEND_EVERY", timedelta(milliseconds=10),
    )

    async def download_that_absorbs_its_first_stop() -> None:
        new_holder_locks = download_locks(another_process)
        async with single_flight_download(settled_redis, "sft", "job-1"):
            await another_process.zrem(new_holder_locks.keys.expiry, "sft")
            assert await new_holder_locks.acquire("sft") is not None
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                pass
            await asyncio.sleep(30)

    async def scenario() -> None:
        async with asyncio.timeout(10):
            await download_that_absorbs_its_first_stop()

    scenario_run = scenario()
    with pytest.raises(DownloadLockLost):
        event_loop.run_until_complete(scenario_run)
