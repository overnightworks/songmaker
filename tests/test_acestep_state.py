"""Tests for ACE-Step Redis state helpers (web container side)."""

from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis
import pytest

from songmaker_cli.acestep_state import (
    ADMIT_GENERATION_SCRIPT,
    DOWNLOAD_KEY_PREFIX,
    GPU_HOLD_KEY_PREFIX,
    QUEUE_KEY_PREFIX,
    RELEASE_GPU_HOLD_SCRIPT,
    RENEW_GPU_HOLD_SCRIPT,
    RESERVE_GPU_HOLD_SCRIPT,
    WORKER_KEY_PREFIX,
    admit_generation,
    clear_download_in_progress,
    decr_queue_depth,
    download_key,
    gpu_hold_key,
    incr_queue_depth,
    queue_depth_key,
    read_download_in_progress,
    read_queue_depth,
    read_worker_state,
    release_gpu_hold,
    renew_gpu_hold,
    reserve_gpu_hold,
    set_download_in_progress,
    worker_is_online,
    worker_state_key,
)


@pytest.fixture()
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
def redis():
    return fakeredis.aioredis.FakeRedis()


def test_key_prefixes_match_worker_heartbeat() -> None:
    from acestep_worker.heartbeat import (
        ADMIT_GENERATION_SCRIPT as WORKER_ADMIT_GENERATION_SCRIPT,
    )
    from acestep_worker.heartbeat import (
        GPU_HOLD_KEY_PREFIX as WORKER_GPU_HOLD_PREFIX,
    )
    from acestep_worker.heartbeat import (
        QUEUE_KEY_PREFIX as WORKER_QUEUE_PREFIX,
    )
    from acestep_worker.heartbeat import (
        RELEASE_GPU_HOLD_SCRIPT as WORKER_RELEASE_GPU_HOLD_SCRIPT,
    )
    from acestep_worker.heartbeat import (
        RENEW_GPU_HOLD_SCRIPT as WORKER_RENEW_GPU_HOLD_SCRIPT,
    )
    from acestep_worker.heartbeat import (
        RESERVE_GPU_HOLD_SCRIPT as WORKER_RESERVE_GPU_HOLD_SCRIPT,
    )
    from acestep_worker.heartbeat import (
        WORKER_KEY_PREFIX as WORKER_WORKER_PREFIX,
    )

    assert WORKER_KEY_PREFIX == WORKER_WORKER_PREFIX
    assert QUEUE_KEY_PREFIX == WORKER_QUEUE_PREFIX
    assert GPU_HOLD_KEY_PREFIX == WORKER_GPU_HOLD_PREFIX
    assert ADMIT_GENERATION_SCRIPT == WORKER_ADMIT_GENERATION_SCRIPT
    assert RESERVE_GPU_HOLD_SCRIPT == WORKER_RESERVE_GPU_HOLD_SCRIPT
    assert RENEW_GPU_HOLD_SCRIPT == WORKER_RENEW_GPU_HOLD_SCRIPT
    assert RELEASE_GPU_HOLD_SCRIPT == WORKER_RELEASE_GPU_HOLD_SCRIPT


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

    fake_redis = MagicMock()

    async def _zero_queue(*_args, **_kwargs):
        return 0

    fake_redis.get = _zero_queue
    deps = WorkerDeps(
        worker_id="acestep-worker-0",
        cache=cache,
        task_store=MagicMock(),
        heartbeat=MagicMock(),
        redis=fake_redis,
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
    assert len(state.loaded) == 1 and state.loaded[0].mode == "sft", (
        f"writer/reader key mismatch: payload has keys {sorted(payload.keys())}, "
        f"reader expects 'loaded' as list[LoadedModelDetail]"
    )
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
        pytest.param({"vram_measured": True}, True, id="measured"),
        pytest.param({"vram_measured": False}, False, id="estimated"),
        pytest.param({}, None, id="legacy-payload-missing-field"),
    ],
)
def test_state_from_dict_reads_vram_measured(
    payload_vram_measured: dict, expected: bool | None
) -> None:
    from songmaker_cli.admin_api import _state_from_dict

    state = _state_from_dict(payload_vram_measured, queue_depth=0)

    assert state is not None
    assert state.vram_measured is expected


def test_worker_state_key_format() -> None:
    assert worker_state_key("acestep-worker-0") == "songmaker:acestep:worker:acestep-worker-0"


def test_queue_depth_key_format() -> None:
    assert queue_depth_key("acestep-worker-0") == "songmaker:acestep:queue:acestep-worker-0"


def test_gpu_hold_key_format() -> None:
    assert gpu_hold_key("acestep-worker-0") == "songmaker:acestep:hold:acestep-worker-0"
    assert GPU_HOLD_KEY_PREFIX == "songmaker:acestep:hold"


def test_reserve_wins_against_a_later_generation_admit(redis, event_loop) -> None:
    assert event_loop.run_until_complete(reserve_gpu_hold(redis, "w1", "token", 15))

    assert not event_loop.run_until_complete(admit_generation(redis, "w1"))
    assert event_loop.run_until_complete(read_queue_depth(redis, "w1")) == 0


def test_generation_admit_wins_against_a_later_hold_reserve(redis, event_loop) -> None:
    assert event_loop.run_until_complete(admit_generation(redis, "w1"))

    assert not event_loop.run_until_complete(reserve_gpu_hold(redis, "w1", "token", 15))
    assert event_loop.run_until_complete(read_queue_depth(redis, "w1")) == 1


def test_hold_token_controls_renew_and_release(redis, event_loop) -> None:
    assert event_loop.run_until_complete(reserve_gpu_hold(redis, "w1", "token", 15))
    assert event_loop.run_until_complete(redis.ttl(gpu_hold_key("w1"))) == 15
    assert not event_loop.run_until_complete(renew_gpu_hold(redis, "w1", "wrong", 15))
    assert not event_loop.run_until_complete(release_gpu_hold(redis, "w1", "wrong"))
    assert event_loop.run_until_complete(renew_gpu_hold(redis, "w1", "token", 15))
    assert event_loop.run_until_complete(release_gpu_hold(redis, "w1", "token"))
    assert event_loop.run_until_complete(admit_generation(redis, "w1"))


def test_read_worker_state_missing(redis, event_loop) -> None:
    result = event_loop.run_until_complete(read_worker_state(redis, "missing"))
    assert result is None


def test_read_worker_state_present(redis, event_loop) -> None:
    payload = {"loaded": ["xl-sft"], "target_loading": None, "vram_used_gb": 12.4}
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


def test_incr_decr_queue_depth(redis, event_loop) -> None:
    assert event_loop.run_until_complete(incr_queue_depth(redis, "w1")) == 1
    assert event_loop.run_until_complete(incr_queue_depth(redis, "w1")) == 2
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


def test_set_then_read_download_in_progress(redis, event_loop) -> None:
    event_loop.run_until_complete(set_download_in_progress(redis, "xl-sft", "job-abc"))
    assert event_loop.run_until_complete(read_download_in_progress(redis, "xl-sft")) == "job-abc"


def test_clear_download_in_progress(redis, event_loop) -> None:
    event_loop.run_until_complete(set_download_in_progress(redis, "sft", "job-1"))
    event_loop.run_until_complete(clear_download_in_progress(redis, "sft"))
    assert event_loop.run_until_complete(read_download_in_progress(redis, "sft")) is None


def test_clear_download_in_progress_idempotent(redis, event_loop) -> None:
    event_loop.run_until_complete(clear_download_in_progress(redis, "never-set"))
    assert event_loop.run_until_complete(read_download_in_progress(redis, "never-set")) is None


def test_set_download_in_progress_has_ttl(redis, event_loop) -> None:
    from songmaker_cli.acestep_state import DOWNLOAD_TTL_SECONDS

    event_loop.run_until_complete(set_download_in_progress(redis, "turbo", "job-x"))
    ttl = event_loop.run_until_complete(redis.ttl(download_key("turbo")))
    assert 0 < ttl <= DOWNLOAD_TTL_SECONDS


def test_set_download_in_progress_returns_true_on_acquire(redis, event_loop) -> None:
    acquired = event_loop.run_until_complete(
        set_download_in_progress(redis, "sft", "job-1"),
    )
    assert acquired is True


def test_set_download_in_progress_returns_false_when_already_set(
    redis,
    event_loop,
) -> None:
    event_loop.run_until_complete(set_download_in_progress(redis, "sft", "job-1"))
    again = event_loop.run_until_complete(
        set_download_in_progress(redis, "sft", "job-2"),
    )
    assert again is False
    assert event_loop.run_until_complete(read_download_in_progress(redis, "sft")) == "job-1"
