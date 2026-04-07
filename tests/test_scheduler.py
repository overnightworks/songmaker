"""Tests for the scheduler — pick_worker, dispatch_generation, SSE consumption."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from acestep_engine.models import AceStepConfig
from songmaker_cli.acestep_state import queue_depth_key, worker_state_key
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.queries import register_worker
from songmaker_cli.scheduler import (
    DispatchOptions,
    GenerationTaskResultDTO,
    NoCapacityError,
    WorkerTaskFailed,
    _pick_from,
    _PickedWorker,
    consume_task_stream,
    dispatch_generation,
    pick_worker,
)


def _run(coro):
    return asyncio.run(coro)


class _InMemoryRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def incr(self, key):
        cur = int(self.store.get(key, 0)) + 1
        self.store[key] = str(cur)
        return cur

    async def decr(self, key):
        cur = int(self.store.get(key, 0)) - 1
        self.store[key] = str(cur)
        return cur


@pytest.fixture()
def db_session(tmp_path: Path):
    factory = init_db(tmp_path / "scheduler.db")
    session = factory()
    yield session
    session.close()


def _seed(session, worker_id: str, *, host="h", port=8001):
    register_worker(
        session,
        worker_id=worker_id,
        host=host,
        port=port,
        gpu_id=0,
        vram_total_gb=24.0,
    )
    session.commit()


def _set_state(redis, worker_id: str, state: dict) -> None:
    redis.store[worker_state_key(worker_id)] = json.dumps(state)


def _set_queue(redis, worker_id: str, depth: int) -> None:
    redis.store[queue_depth_key(worker_id)] = str(depth)


def _make_picked(wid="w1", host="h", port=8001, loaded=None, depth=0):
    return _PickedWorker(
        id=wid, host=host, port=port,
        loaded_modes=loaded or [], queue_depth=depth,
    )


# ── pick_worker ─────────────────────────────────────────────────────


def test_pick_from_no_workers_raises() -> None:
    with pytest.raises(NoCapacityError):
        _pick_from([], "sft")


def test_pick_from_prefers_loaded() -> None:
    a = _make_picked("a", loaded=["sft"], depth=10)
    b = _make_picked("b", loaded=[], depth=0)
    assert _pick_from([a, b], "sft").id == "a"


def test_pick_from_falls_back_to_least_busy() -> None:
    a = _make_picked("a", loaded=[], depth=5)
    b = _make_picked("b", loaded=[], depth=2)
    c = _make_picked("c", loaded=[], depth=10)
    assert _pick_from([a, b, c], "sft").id == "b"


def test_pick_from_picks_least_busy_among_loaded() -> None:
    a = _make_picked("a", loaded=["sft"], depth=5)
    b = _make_picked("b", loaded=["sft"], depth=2)
    c = _make_picked("c", loaded=[], depth=0)
    assert _pick_from([a, b, c], "sft").id == "b"


def test_pick_worker_skips_offline(db_session) -> None:
    _seed(db_session, "online-w", host="h1")
    _seed(db_session, "offline-w", host="h2")
    redis = _InMemoryRedis()
    _set_state(redis, "online-w", {"loaded": ["sft"]})

    picked = _run(pick_worker(db_session, redis, "sft"))
    assert picked.id == "online-w"


def test_pick_worker_no_online_raises(db_session) -> None:
    _seed(db_session, "w1")
    redis = _InMemoryRedis()
    with pytest.raises(NoCapacityError):
        _run(pick_worker(db_session, redis, "sft"))


# ── consume_task_stream ────────────────────────────────────────────


def _build_sse_response(*events: tuple[str, dict]) -> bytes:
    chunks = []
    for event_type, data in events:
        chunks.append(f"event: {event_type}\ndata: {json.dumps(data)}\n\n")
    return "".join(chunks).encode()


def _make_stream_client(events_or_exc) -> AsyncMock:
    if isinstance(events_or_exc, Exception):
        async def _aiter_text():  # noqa: D401
            raise events_or_exc
            yield ""  # pragma: no cover
    else:
        body = "".join(
            f"event: {t}\ndata: {json.dumps(d)}\n\n" for t, d in events_or_exc
        )

        async def _aiter_text():
            yield body

    stream_resp = AsyncMock()
    stream_resp.raise_for_status = MagicMock()
    stream_resp.aiter_text = _aiter_text
    stream_resp.__aenter__ = AsyncMock(return_value=stream_resp)
    stream_resp.__aexit__ = AsyncMock(return_value=False)

    client = AsyncMock()
    client.stream = MagicMock(return_value=stream_resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _patch_async_client(client_mock):
    return patch("songmaker_cli.scheduler.httpx.AsyncClient", return_value=client_mock)


def test_consume_task_stream_done_returns_dto() -> None:
    worker = _make_picked()
    done_payload = {
        "task_id": "gen-1",
        "result": {
            "mode": "sft",
            "audio_path": "/app/data/audio/worker_output/gen-1-abc.wav",
            "seed": 42,
            "cot_caption": "",
            "cot_lyrics": "",
        },
    }
    client = _make_stream_client([("done", done_payload)])

    with _patch_async_client(client):
        result = _run(consume_task_stream(worker, "gen-1"))

    assert isinstance(result, GenerationTaskResultDTO)
    assert result.seed == 42
    assert result.audio_path.endswith(".wav")


def test_consume_task_stream_error_raises() -> None:
    worker = _make_picked()
    client = _make_stream_client([("error", {"error": "GPU OOM"})])
    with _patch_async_client(client):
        with pytest.raises(WorkerTaskFailed, match="GPU OOM"):
            _run(consume_task_stream(worker, "gen-1"))


def test_consume_task_stream_progress_calls_callback() -> None:
    worker = _make_picked()
    captured: list[float] = []

    async def on_progress(fraction: float) -> None:
        captured.append(fraction)

    events = [
        ("progress", {"progress": 0.2}),
        ("progress", {"progress": 0.5}),
        ("done", {
            "task_id": "g",
            "result": {"mode": "sft", "audio_path": "/x.wav", "seed": 1},
        }),
    ]
    client = _make_stream_client(events)
    with _patch_async_client(client):
        _run(consume_task_stream(worker, "gen-1", on_progress=on_progress))

    assert captured == [0.2, 0.5]


def test_consume_task_stream_invalid_result_raises() -> None:
    worker = _make_picked()
    client = _make_stream_client([("done", {"task_id": "g", "result": {"mode": "sft"}})])
    with _patch_async_client(client):
        with pytest.raises(WorkerTaskFailed, match="invalid result"):
            _run(consume_task_stream(worker, "gen-1"))


def test_consume_task_stream_reconnects_on_transport_drop() -> None:
    worker = _make_picked()

    bad_client = _make_stream_client(httpx.ConnectError("refused"))

    good_events = [(
        "done",
        {
            "task_id": "g",
            "result": {
                "mode": "sft", "audio_path": "/x.wav", "seed": 1,
            },
        },
    )]
    good_client = _make_stream_client(good_events)

    clients = iter([bad_client, good_client])

    def _factory(*args, **kwargs):
        return next(clients)

    options = DispatchOptions(
        max_sse_reconnects=2,
        initial_reconnect_backoff_seconds=0.0,
        max_reconnect_backoff_seconds=0.0,
    )
    with patch("songmaker_cli.scheduler.httpx.AsyncClient", side_effect=_factory):
        result = _run(consume_task_stream(worker, "gen-1", options=options))
    assert result.seed == 1


def test_consume_task_stream_gives_up_after_max_reconnects() -> None:
    worker = _make_picked()

    def _factory(*args, **kwargs):
        return _make_stream_client(httpx.ConnectError("refused"))

    options = DispatchOptions(
        max_sse_reconnects=2,
        initial_reconnect_backoff_seconds=0.0,
        max_reconnect_backoff_seconds=0.0,
    )
    with patch("songmaker_cli.scheduler.httpx.AsyncClient", side_effect=_factory):
        with pytest.raises(httpx.ConnectError):
            _run(consume_task_stream(worker, "gen-1", options=options))


# ── dispatch_generation ────────────────────────────────────────────


def _make_ace_config():
    return AceStepConfig(prompt="x", lyrics="la la", duration=60)


def test_dispatch_increments_then_decrements_queue_depth(db_session) -> None:
    _seed(db_session, "w1")
    redis = _InMemoryRedis()
    _set_state(redis, "w1", {"loaded": ["sft"]})

    done = [(
        "done",
        {"task_id": "g", "result": {"mode": "sft", "audio_path": "/x.wav", "seed": 1}},
    )]
    client = _make_stream_client(done)

    with patch("songmaker_cli.scheduler.httpx.AsyncClient", return_value=client):
        with patch(
            "songmaker_cli.scheduler._submit_generation",
            new=AsyncMock(return_value="gen-1"),
        ):
            _run(dispatch_generation(
                ace_config=_make_ace_config(),
                target_mode="sft",
                redis=redis,
                db=db_session,
            ))

    assert int(redis.store[queue_depth_key("w1")]) == 0


def test_dispatch_decrements_on_failure(db_session) -> None:
    _seed(db_session, "w1")
    redis = _InMemoryRedis()
    _set_state(redis, "w1", {"loaded": ["sft"]})

    with patch(
        "songmaker_cli.scheduler._submit_generation",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            _run(dispatch_generation(
                ace_config=_make_ace_config(),
                target_mode="sft",
                redis=redis,
                db=db_session,
            ))

    assert int(redis.store[queue_depth_key("w1")]) == 0


def test_dispatch_loads_model_if_not_loaded(db_session) -> None:
    _seed(db_session, "w1")
    redis = _InMemoryRedis()
    _set_state(redis, "w1", {"loaded": []})

    load_calls: list[str] = []

    async def _fake_ensure_loaded(worker, target_mode, options):
        load_calls.append(target_mode)

    done = [(
        "done",
        {"task_id": "g", "result": {"mode": "sft", "audio_path": "/x.wav", "seed": 1}},
    )]
    client = _make_stream_client(done)

    with (
        patch("songmaker_cli.scheduler._ensure_loaded", new=_fake_ensure_loaded),
        patch(
            "songmaker_cli.scheduler._submit_generation",
            new=AsyncMock(return_value="gen-1"),
        ),
        patch("songmaker_cli.scheduler.httpx.AsyncClient", return_value=client),
    ):
        _run(dispatch_generation(
            ace_config=_make_ace_config(),
            target_mode="sft",
            redis=redis,
            db=db_session,
        ))

    assert load_calls == ["sft"]


def test_dispatch_skips_load_when_already_loaded(db_session) -> None:
    _seed(db_session, "w1")
    redis = _InMemoryRedis()
    _set_state(redis, "w1", {"loaded": ["sft"]})

    load_called = False

    async def _fake_ensure_loaded(worker, target_mode, options):
        nonlocal load_called
        if target_mode not in worker.loaded_modes:
            load_called = True

    done = [(
        "done",
        {"task_id": "g", "result": {"mode": "sft", "audio_path": "/x.wav", "seed": 1}},
    )]
    client = _make_stream_client(done)

    with (
        patch("songmaker_cli.scheduler._ensure_loaded", new=_fake_ensure_loaded),
        patch(
            "songmaker_cli.scheduler._submit_generation",
            new=AsyncMock(return_value="gen-1"),
        ),
        patch("songmaker_cli.scheduler.httpx.AsyncClient", return_value=client),
    ):
        _run(dispatch_generation(
            ace_config=_make_ace_config(),
            target_mode="sft",
            redis=redis,
            db=db_session,
        ))

    assert load_called is False


# ── DTO drift ──────────────────────────────────────────────────────


def test_dto_keys_match_worker_model_fields() -> None:
    from acestep_worker.models import GenerationTaskResult

    assert (
        GenerationTaskResult.model_fields.keys()
        == GenerationTaskResultDTO.model_fields.keys()
    )


# ── _ensure_loaded + _submit_generation (httpx unit tests) ─────────


def test_ensure_loaded_skips_when_already_loaded() -> None:
    worker = _make_picked(loaded=["sft"])
    with patch("songmaker_cli.scheduler.httpx.AsyncClient") as cls:
        from songmaker_cli.scheduler import _ensure_loaded
        _run(_ensure_loaded(worker, "sft", DispatchOptions()))
    cls.assert_not_called()


def test_ensure_loaded_posts_when_missing() -> None:
    worker = _make_picked(loaded=[])
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    client = AsyncMock()
    client.post = AsyncMock(return_value=fake_response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    from songmaker_cli.scheduler import _ensure_loaded
    with patch("songmaker_cli.scheduler.httpx.AsyncClient", return_value=client):
        _run(_ensure_loaded(worker, "sft", DispatchOptions()))

    client.post.assert_called_once()
    args, kwargs = client.post.call_args
    assert args[0].endswith("/load_model")
    assert kwargs["json"] == {"mode": "sft"}


def test_submit_generation_returns_task_id() -> None:
    worker = _make_picked()
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json = MagicMock(return_value={"task_id": "gen-1"})
    client = AsyncMock()
    client.post = AsyncMock(return_value=fake_response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    from songmaker_cli.scheduler import _submit_generation
    with patch("songmaker_cli.scheduler.httpx.AsyncClient", return_value=client):
        task_id = _run(_submit_generation(
            worker, _make_ace_config(), "sft", DispatchOptions(),
        ))
    assert task_id == "gen-1"
    args, kwargs = client.post.call_args
    assert args[0].endswith("/generate")
    assert kwargs["json"]["mode"] == "sft"
    assert "config" in kwargs["json"]
