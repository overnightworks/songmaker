"""Tests for the scheduler — pick_worker, dispatch_generation, SSE consumption."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
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
    DownloadTaskResultDTO,
    GenerationTaskResultDTO,
    NoCapacityError,
    WorkerGenerationFailed,
    WorkerProtocolError,
    WorkerTaskFailed,
    _iterate_task_events,
    _pick_from,
    _PickedWorker,
    consume_download_task_stream,
    consume_task_stream,
    dispatch_generation,
    pick_any_online_worker,
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
def db_factory(tmp_path: Path):
    yield init_db(tmp_path / "scheduler.db")


@pytest.fixture()
def db_session(db_factory):
    session = db_factory()
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


def _set_state(
    redis, worker_id: str, state: dict, *, gpu_healthy: bool | None = True,
) -> None:
    """Write a worker heartbeat. Defaults to a healthy GPU so the many tests
    unrelated to issue #367 don't need to know about it; pass
    gpu_healthy=None to omit the key entirely (simulating an old worker
    build) or gpu_healthy=False to simulate a broken one — the latter reads
    more naturally as an explicit "gpu_healthy": False in the state dict,
    which this never overrides."""
    payload = dict(state)
    if gpu_healthy is not None:
        payload.setdefault("gpu_healthy", gpu_healthy)
    redis.store[worker_state_key(worker_id)] = json.dumps(payload)


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


def test_pick_worker_skips_worker_with_broken_gpu(db_session) -> None:
    """Issue #367: a worker whose GPU has gone away (NVML present but
    unreachable) keeps heartbeating fine, so heartbeat presence alone must
    not make it a candidate. Simulated via gpu_healthy: False in the
    heartbeat, never a lucky real GPU — the scheduler must route the job to
    its healthy neighbor instead."""
    _seed(db_session, "broken-gpu-w", host="h1")
    _seed(db_session, "healthy-w", host="h2")
    redis = _InMemoryRedis()
    _set_state(redis, "broken-gpu-w", {"loaded": ["sft"], "gpu_healthy": False})
    _set_state(redis, "healthy-w", {"loaded": ["sft"], "gpu_healthy": True})

    picked = _run(pick_worker(db_session, redis, "sft"))
    assert picked.id == "healthy-w"


def test_pick_worker_no_online_when_only_worker_has_broken_gpu(db_session) -> None:
    _seed(db_session, "broken-gpu-w")
    redis = _InMemoryRedis()
    _set_state(redis, "broken-gpu-w", {"loaded": ["sft"], "gpu_healthy": False})
    with pytest.raises(NoCapacityError):
        _run(pick_worker(db_session, redis, "sft"))


def test_pick_worker_missing_gpu_healthy_field_is_treated_as_not_online(db_session) -> None:
    """Fail-closed: a heartbeat with no gpu_healthy key at all (an old or
    broken worker build that never learned to publish it) must never be
    routed a job on the silent assumption that it is fine."""
    _seed(db_session, "w1")
    redis = _InMemoryRedis()
    _set_state(redis, "w1", {"loaded": ["sft"]}, gpu_healthy=None)
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


def test_consume_task_stream_error_raises_with_the_workers_own_cause() -> None:
    worker = _make_picked()
    client = _make_stream_client([("error", {"error": "GPU OOM"})])
    with _patch_async_client(client):
        with pytest.raises(WorkerGenerationFailed) as exc_info:
            _run(consume_task_stream(worker, "gen-1"))
    assert str(exc_info.value) == "GPU OOM"


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


def test_consume_task_stream_done_missing_result_raises_protocol_error() -> None:
    worker = _make_picked()
    client = _make_stream_client([("done", {"task_id": "g"})])
    with _patch_async_client(client):
        with pytest.raises(WorkerProtocolError, match="missing 'result'"):
            _run(consume_task_stream(worker, "gen-1"))


def test_consume_task_stream_error_missing_field_raises_protocol_error() -> None:
    worker = _make_picked()
    client = _make_stream_client([("error", {"task_id": "g"})])
    with _patch_async_client(client):
        with pytest.raises(WorkerProtocolError, match="missing 'error'"):
            _run(consume_task_stream(worker, "gen-1"))


@pytest.mark.parametrize(
    "consume", [consume_task_stream, consume_download_task_stream],
    ids=["generation", "download"],
)
def test_consume_task_stream_empty_error_is_a_protocol_error_for_both_task_kinds(
    consume, caplog: pytest.LogCaptureFixture,
) -> None:
    """An empty 'error' field carries no cause, so it must not be relayed
    as one, for either task kind: the worker always sends text, and the job
    layer shows the message verbatim. Download previously diverged here,
    raising ``WorkerTaskFailed('')`` instead — issue #227 unifies both
    consumers on the shared ``_consume_task_stream`` implementation."""
    worker = _make_picked()
    client = _make_stream_client([("error", {"error": ""})])
    with _patch_async_client(client):
        with caplog.at_level("WARNING", logger="songmaker_cli.scheduler"):
            with pytest.raises(WorkerProtocolError, match="empty 'error'"):
                _run(consume(worker, "task-1"))
    assert any("empty 'error'" in r.message for r in caplog.records)


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
    return AceStepConfig(prompt="x", lyrics="la la", audio_duration=60)


def test_dispatch_increments_then_decrements_queue_depth(db_factory, db_session) -> None:
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
                db_factory=db_factory,
            ))

    assert int(redis.store[queue_depth_key("w1")]) == 0


def test_dispatch_decrements_on_failure(db_factory, db_session) -> None:
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
                db_factory=db_factory,
            ))

    assert int(redis.store[queue_depth_key("w1")]) == 0


def test_dispatch_loads_model_if_not_loaded(db_factory, db_session) -> None:
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
            db_factory=db_factory,
        ))

    assert load_calls == ["sft"]


def test_dispatch_skips_load_when_already_loaded(db_factory, db_session) -> None:
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
            db_factory=db_factory,
        ))

    assert load_called is False


def test_dispatch_session_closed_before_sse(db_factory) -> None:
    """Regression: dispatch_generation must NOT hold a DB session open across
    the SSE consumption phase. The session is only needed for pick_worker."""
    with db_factory() as session:
        _seed(session, "w1")

    redis = _InMemoryRedis()
    _set_state(redis, "w1", {"loaded": ["sft"]})

    enter_count = 0
    exit_count = 0
    real_factory = db_factory

    class _TrackingSession:
        def __init__(self) -> None:
            self._inner = real_factory()

        def __enter__(self):
            nonlocal enter_count
            enter_count += 1
            self._inner.__enter__()
            return self._inner

        def __exit__(self, *args):
            nonlocal exit_count
            exit_count += 1
            return self._inner.__exit__(*args)

    def _tracking_factory():
        return _TrackingSession()

    done = [(
        "done",
        {"task_id": "g", "result": {"mode": "sft", "audio_path": "/x.wav", "seed": 1}},
    )]
    client = _make_stream_client(done)

    async def _checked_submit(*args, **kwargs):
        assert exit_count == enter_count, (
            "all sessions must be closed before SSE/HTTP phase"
        )
        assert exit_count >= 1, "pick_worker must have opened a session"
        return "gen-1"

    with (
        patch("songmaker_cli.scheduler._submit_generation", new=_checked_submit),
        patch("songmaker_cli.scheduler.httpx.AsyncClient", return_value=client),
    ):
        _run(dispatch_generation(
            ace_config=_make_ace_config(),
            target_mode="sft",
            redis=redis,
            db_factory=_tracking_factory,
        ))

    assert enter_count == 1


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
    assert kwargs["json"]["config"] == asdict(_make_ace_config())


# ── _iterate_task_events ─────────────────────────────────────────────


def test_iterate_task_events_yields_in_order() -> None:
    worker = _make_picked()
    events = [
        ("progress", {"progress": 0.25}),
        ("progress", {"progress": 0.75}),
        ("done", {"task_id": "t", "result": {"mode": "sft", "size_bytes": 100}}),
    ]
    client = _make_stream_client(events)

    async def collect():
        out: list[tuple[str, dict]] = []
        with _patch_async_client(client):
            async for evt in _iterate_task_events(worker, "t"):
                out.append(evt)
        return out

    result = _run(collect())
    assert [e[0] for e in result] == ["progress", "progress", "done"]
    assert result[0][1] == {"progress": 0.25}
    assert result[2][1]["result"]["mode"] == "sft"


def test_iterate_task_events_stops_after_done() -> None:
    worker = _make_picked()
    events = [
        ("done", {"task_id": "t", "result": {"mode": "sft", "size_bytes": 1}}),
        ("progress", {"progress": 0.99}),
    ]
    client = _make_stream_client(events)

    async def collect():
        out: list[tuple[str, dict]] = []
        with _patch_async_client(client):
            async for evt in _iterate_task_events(worker, "t"):
                out.append(evt)
        return out

    result = _run(collect())
    assert len(result) == 1
    assert result[0][0] == "done"


def test_iterate_task_events_stops_after_error() -> None:
    worker = _make_picked()
    events = [
        ("error", {"error": "boom"}),
        ("progress", {"progress": 0.99}),
    ]
    client = _make_stream_client(events)

    async def collect():
        out: list[tuple[str, dict]] = []
        with _patch_async_client(client):
            async for evt in _iterate_task_events(worker, "t"):
                out.append(evt)
        return out

    result = _run(collect())
    assert len(result) == 1
    assert result[0][0] == "error"


def test_iterate_task_events_reconnect_on_transport_drop() -> None:
    worker = _make_picked()
    bad_client = _make_stream_client(httpx.ConnectError("refused"))
    good_client = _make_stream_client([
        ("done", {"task_id": "t", "result": {"mode": "sft", "size_bytes": 1}}),
    ])
    clients = iter([bad_client, good_client])

    def _factory(*args, **kwargs):
        return next(clients)

    options = DispatchOptions(
        max_sse_reconnects=2,
        initial_reconnect_backoff_seconds=0.0,
        max_reconnect_backoff_seconds=0.0,
    )

    async def collect():
        out: list[tuple[str, dict]] = []
        with patch("songmaker_cli.scheduler.httpx.AsyncClient", side_effect=_factory):
            async for evt in _iterate_task_events(worker, "t", options=options):
                out.append(evt)
        return out

    result = _run(collect())
    assert len(result) == 1
    assert result[0][0] == "done"


def test_iterate_task_events_max_reconnects_exhausted() -> None:
    worker = _make_picked()

    def _factory(*args, **kwargs):
        return _make_stream_client(httpx.ConnectError("refused"))

    options = DispatchOptions(
        max_sse_reconnects=2,
        initial_reconnect_backoff_seconds=0.0,
        max_reconnect_backoff_seconds=0.0,
    )

    async def collect():
        with patch("songmaker_cli.scheduler.httpx.AsyncClient", side_effect=_factory):
            async for _evt in _iterate_task_events(worker, "t", options=options):
                pass

    with pytest.raises(httpx.ConnectError):
        _run(collect())


# ── pick_any_online_worker ───────────────────────────────────────────


def test_pick_any_online_worker_returns_lowest_id(db_session) -> None:
    _seed(db_session, "w-c")
    _seed(db_session, "w-a")
    _seed(db_session, "w-b")
    redis = _InMemoryRedis()
    _set_state(redis, "w-c", {"loaded": []})
    _set_state(redis, "w-a", {"loaded": []})
    _set_state(redis, "w-b", {"loaded": []})

    result = _run(pick_any_online_worker(db_session, redis))
    assert result.id == "w-a"


def test_pick_any_online_worker_skips_offline(db_session) -> None:
    _seed(db_session, "w1")
    _seed(db_session, "w2")
    redis = _InMemoryRedis()
    _set_state(redis, "w2", {"loaded": []})

    result = _run(pick_any_online_worker(db_session, redis))
    assert result.id == "w2"


def test_pick_any_online_worker_no_workers_raises(db_session) -> None:
    redis = _InMemoryRedis()
    with pytest.raises(NoCapacityError):
        _run(pick_any_online_worker(db_session, redis))


# ── consume_download_task_stream ─────────────────────────────────────


def test_consume_download_task_stream_done_returns_dto() -> None:
    worker = _make_picked()
    events = [
        ("done", {"task_id": "d", "result": {"mode": "xl-sft", "size_bytes": 13_000_000_000}}),
    ]
    client = _make_stream_client(events)
    with _patch_async_client(client):
        result = _run(consume_download_task_stream(worker, "d"))
    assert isinstance(result, DownloadTaskResultDTO)
    assert result.mode == "xl-sft"
    assert result.size_bytes == 13_000_000_000


def test_consume_download_task_stream_error_raises() -> None:
    worker = _make_picked()
    client = _make_stream_client([("error", {"error": "HF 401 unauthorized"})])
    with _patch_async_client(client):
        with pytest.raises(WorkerTaskFailed, match="HF 401"):
            _run(consume_download_task_stream(worker, "d"))


def test_consume_download_task_stream_progress_calls_callback() -> None:
    worker = _make_picked()
    captured: list[float] = []

    async def on_progress(fraction: float) -> None:
        captured.append(fraction)

    events = [
        ("progress", {"progress": 0.1}),
        ("progress", {"progress": 0.5}),
        ("progress", {"progress": 0.9}),
        ("done", {"task_id": "d", "result": {"mode": "sft", "size_bytes": 100}}),
    ]
    client = _make_stream_client(events)
    with _patch_async_client(client):
        _run(consume_download_task_stream(worker, "d", on_progress=on_progress))

    assert captured == [0.1, 0.5, 0.9]


def test_consume_download_task_stream_invalid_payload_raises() -> None:
    worker = _make_picked()
    client = _make_stream_client([("done", {"task_id": "d", "result": {"mode": "sft"}})])
    with _patch_async_client(client):
        with pytest.raises(WorkerTaskFailed, match="invalid download result"):
            _run(consume_download_task_stream(worker, "d"))


def test_consume_download_task_stream_done_missing_result_raises_protocol_error() -> None:
    worker = _make_picked()
    client = _make_stream_client([("done", {"task_id": "d"})])
    with _patch_async_client(client):
        with pytest.raises(WorkerProtocolError, match="missing 'result'"):
            _run(consume_download_task_stream(worker, "d"))


def test_consume_download_task_stream_error_missing_field_raises_protocol_error() -> None:
    worker = _make_picked()
    client = _make_stream_client([("error", {"task_id": "d"})])
    with _patch_async_client(client):
        with pytest.raises(WorkerProtocolError, match="missing 'error'"):
            _run(consume_download_task_stream(worker, "d"))


def test_consume_download_task_stream_heartbeat_on_every_event() -> None:
    worker = _make_picked()
    heartbeats = 0

    def on_heartbeat() -> None:
        nonlocal heartbeats
        heartbeats += 1

    events = [
        ("progress", {"progress": 0.25}),
        ("progress", {"progress": 0.75}),
        ("done", {"task_id": "d", "result": {"mode": "sft", "size_bytes": 1}}),
    ]
    client = _make_stream_client(events)
    with _patch_async_client(client):
        _run(consume_download_task_stream(worker, "d", on_heartbeat=on_heartbeat))

    assert heartbeats == 3


def test_consume_download_task_stream_empty_stream_raises() -> None:
    worker = _make_picked()
    client = _make_stream_client([])
    with _patch_async_client(client):
        with pytest.raises(WorkerTaskFailed, match="ended without"):
            _run(consume_download_task_stream(worker, "d"))
