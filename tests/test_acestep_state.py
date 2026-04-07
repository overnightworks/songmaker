"""Tests for ACE-Step Redis state helpers (web container side)."""

from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis
import pytest

from songmaker_cli.acestep_state import (
    QUEUE_KEY_PREFIX,
    WORKER_KEY_PREFIX,
    decr_queue_depth,
    incr_queue_depth,
    list_worker_states,
    queue_depth_key,
    read_queue_depth,
    read_worker_state,
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
        QUEUE_KEY_PREFIX as WORKER_QUEUE_PREFIX,
    )
    from acestep_worker.heartbeat import (
        WORKER_KEY_PREFIX as WORKER_WORKER_PREFIX,
    )

    assert WORKER_KEY_PREFIX == WORKER_WORKER_PREFIX
    assert QUEUE_KEY_PREFIX == WORKER_QUEUE_PREFIX


def test_heartbeat_payload_keys_match_admin_reader() -> None:
    from pathlib import Path
    from unittest.mock import MagicMock

    from acestep_worker.model_cache import ModelCache
    from acestep_worker.wrapper import WorkerDeps, build_state_payload
    from songmaker_cli.admin_api import _state_from_dict

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
        generate_runner=MagicMock(),
    )
    payload = asyncio.run(build_state_payload(deps))

    state = _state_from_dict(payload, queue_depth=0)
    assert state is not None
    assert state.loaded == ["sft"], (
        f"writer/reader key mismatch: payload has keys {sorted(payload.keys())}, "
        f"reader expects 'loaded'"
    )
    assert state.vram_used_gb == 6.0
    assert state.target_loading is None
    assert state.vram_total_gb == 24.0
    assert state.available_modes == []


def test_worker_state_key_format() -> None:
    assert worker_state_key("acestep-worker-0") == "songmaker:acestep:worker:acestep-worker-0"


def test_queue_depth_key_format() -> None:
    assert queue_depth_key("acestep-worker-0") == "songmaker:acestep:queue:acestep-worker-0"


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


def test_read_queue_depth_missing_returns_zero(redis, event_loop) -> None:
    assert event_loop.run_until_complete(read_queue_depth(redis, "w1")) == 0


def test_incr_decr_queue_depth(redis, event_loop) -> None:
    assert event_loop.run_until_complete(incr_queue_depth(redis, "w1")) == 1
    assert event_loop.run_until_complete(incr_queue_depth(redis, "w1")) == 2
    assert event_loop.run_until_complete(read_queue_depth(redis, "w1")) == 2
    assert event_loop.run_until_complete(decr_queue_depth(redis, "w1")) == 1
    assert event_loop.run_until_complete(read_queue_depth(redis, "w1")) == 1


def test_decode_handles_str_branch() -> None:
    from songmaker_cli.acestep_state import _decode

    assert _decode(None) is None
    assert _decode(b"abc") == "abc"
    assert _decode("xyz") == "xyz"


def test_list_worker_states(redis, event_loop) -> None:
    event_loop.run_until_complete(
        redis.set(worker_state_key("w1"), json.dumps({"loaded": ["sft"]})),
    )
    event_loop.run_until_complete(
        redis.set(worker_state_key("w2"), json.dumps({"loaded": ["turbo"]})),
    )
    result = event_loop.run_until_complete(
        list_worker_states(redis, ["w1", "w2", "w3"]),
    )
    assert result["w1"] == {"loaded": ["sft"]}
    assert result["w2"] == {"loaded": ["turbo"]}
    assert result["w3"] is None
