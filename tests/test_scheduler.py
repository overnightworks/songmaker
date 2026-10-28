"""Tests for the scheduler — pick_worker, admission, dispatch, SSE consumption."""

from __future__ import annotations

import asyncio
import json
import socket
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import httpx
import pytest
from worker_http_peer import TransportFailure, WorkerReply, WorkerScenario

from acestep_engine.constants import MODE_NOT_LOADED_DETAIL
from acestep_engine.models import AceStepConfig
from acestep_engine.progress import AceStepPhase
from songmaker_cli.acestep_state import (
    gpu_hold_key,
    queue_depth_key,
    read_queue_depth,
    worker_state_key,
)
from songmaker_cli.constants import (
    ACESTEP_SSE_CONNECT_TIMEOUT_SECONDS,
    GENERATE_LOAD_MODEL_TIMEOUT_SECONDS,
    GENERATE_SUBMIT_TIMEOUT_SECONDS,
)
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.queries.workers import register_worker
from songmaker_cli.scheduler import (
    WORKER_ERROR_GPU_OUT_OF_MEMORY,
    WORKER_STREAM_WENT_SILENT,
    AllWorkersHeld,
    DispatchOptions,
    DownloadTaskResultDTO,
    GenerationTaskResultDTO,
    NoCapacityError,
    WorkerGenerationFailed,
    WorkerGenerationUnavailable,
    WorkerGpuOutOfMemory,
    WorkerModeNotLoaded,
    WorkerProtocolError,
    WorkerTaskFailed,
    _iterate_task_events,
    _pick_from,
    _PickedWorker,
    admit_generation_worker,
    consume_download_task_stream,
    consume_task_stream,
    dispatch_generation_on_worker,
    pick_any_online_worker,
    pick_worker,
)

_SOCKET_SSE_READ_TIMEOUT_SECONDS = 2
_PEER_DISPATCH_OPTIONS = DispatchOptions(
    load_model_timeout_seconds=0.25,
    generate_submit_timeout_seconds=0.25,
    sse_connect_timeout_seconds=0.25,
    sse_read_timeout_seconds=0.25,
    initial_reconnect_backoff_seconds=0.0,
    max_reconnect_backoff_seconds=0.0,
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

    async def exists(self, key):
        return int(key in self.store)

    async def eval(self, script, key_count, *args):
        keys = args[:key_count]
        if "INCR" in script and "EXISTS" in script:
            if keys[1] in self.store:
                return 0
            return await self.incr(keys[0])
        raise AssertionError(f"Unexpected Redis script: {script}")


@pytest.fixture
def db_factory(tmp_path: Path):
    return init_db(tmp_path / "scheduler.db")


@pytest.fixture
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
    redis,
    worker_id: str,
    state: dict,
    *,
    gpu_healthy: bool | None = True,
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
        id=wid,
        host=host,
        port=port,
        loaded_modes=loaded or [],
        queue_depth=depth,
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
    operation = pick_worker(db_session, redis, "sft")
    with pytest.raises(NoCapacityError):
        _run(operation)


def test_pick_worker_defers_when_every_online_worker_is_held(db_session) -> None:
    from songmaker_cli.acestep_state import gpu_hold_key

    _seed(db_session, "w1")
    redis = _InMemoryRedis()
    _set_state(redis, "w1", {"loaded": ["sft"]})
    redis.store[gpu_hold_key("w1")] = "hold-token"
    operation = pick_worker(db_session, redis, "sft")

    with pytest.raises(AllWorkersHeld):
        _run(operation)


def test_admit_generation_uses_redis_lua_without_incrementing_behind_a_hold(db_session) -> None:
    async def exercise() -> None:
        redis = fakeredis.aioredis.FakeRedis()
        _seed(db_session, "w1")
        await redis.set(
            worker_state_key("w1"),
            json.dumps({"gpu_healthy": True, "loaded": ["sft"]}),
        )

        async def pick_then_hold(*_args, **_kwargs):
            await redis.set(gpu_hold_key("w1"), "hold-token")
            return _make_picked("w1")

        with (
            patch("songmaker_cli.scheduler.pick_worker", pick_then_hold),
            pytest.raises(AllWorkersHeld),
        ):
            await admit_generation_worker(
                target_mode="sft",
                redis=redis,
                db_factory=lambda: db_session,
            )
        assert await read_queue_depth(redis, "w1") == 0

    _run(exercise())


def test_admit_generation_closes_its_session_before_the_occupancy_call(db_factory) -> None:
    with db_factory() as session:
        _seed(session, "w1")
    sessions_entered = 0
    sessions_exited = 0

    class _TrackingSession:
        def __init__(self) -> None:
            self._inner = db_factory()

        def __enter__(self):
            nonlocal sessions_entered
            sessions_entered += 1
            return self._inner.__enter__()

        def __exit__(self, *args):
            nonlocal sessions_exited
            sessions_exited += 1
            return self._inner.__exit__(*args)

    class _RedisCheckingSessionsAtEval:
        def __init__(self, inner) -> None:
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def eval(self, *args):
            assert sessions_entered >= 1, "pick_worker must have opened a session"
            assert sessions_exited == sessions_entered, "session still open at the occupancy call"
            return await self._inner.eval(*args)

    async def exercise() -> None:
        fake = fakeredis.aioredis.FakeRedis()
        loaded = [{"mode": "sft", "size_gb": 1.0}]
        await fake.set(worker_state_key("w1"), json.dumps({"gpu_healthy": True, "loaded": loaded}))
        await admit_generation_worker(
            target_mode="sft",
            redis=_RedisCheckingSessionsAtEval(fake),
            db_factory=_TrackingSession,
        )
        assert await read_queue_depth(fake, "w1") == 1

    _run(exercise())
    assert (sessions_entered, sessions_exited) == (1, 1)


def test_pick_worker_skips_a_held_worker_for_a_free_online_worker(db_session) -> None:
    from songmaker_cli.acestep_state import gpu_hold_key

    _seed(db_session, "held", host="h1")
    _seed(db_session, "free", host="h2")
    redis = _InMemoryRedis()
    _set_state(redis, "held", {"loaded": ["sft"]})
    _set_state(redis, "free", {"loaded": []})
    _set_queue(redis, "held", 0)
    _set_queue(redis, "free", 9)
    redis.store[gpu_hold_key("held")] = "hold-token"

    picked = _run(pick_worker(db_session, redis, "sft"))

    assert picked.id == "free"


def test_dispatch_options_use_the_shared_generate_timeout_windows() -> None:
    options = DispatchOptions()

    assert options.load_model_timeout_seconds == GENERATE_LOAD_MODEL_TIMEOUT_SECONDS
    assert options.generate_submit_timeout_seconds == GENERATE_SUBMIT_TIMEOUT_SECONDS
    assert options.sse_connect_timeout_seconds == ACESTEP_SSE_CONNECT_TIMEOUT_SECONDS


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
    operation = pick_worker(db_session, redis, "sft")
    with pytest.raises(NoCapacityError):
        _run(operation)


def test_pick_worker_missing_gpu_healthy_field_is_treated_as_not_online(db_session) -> None:
    """Fail-closed: a heartbeat with no gpu_healthy key at all (an old or
    broken worker build that never learned to publish it) must never be
    routed a job on the silent assumption that it is fine."""
    _seed(db_session, "w1")
    redis = _InMemoryRedis()
    _set_state(redis, "w1", {"loaded": ["sft"]}, gpu_healthy=None)
    operation = pick_worker(db_session, redis, "sft")
    with pytest.raises(NoCapacityError):
        _run(operation)


def test_pick_worker_ignores_unreadable_heartbeat_instead_of_preferring_it(
    db_session,
    caplog,
) -> None:
    _seed(db_session, "renamed-field", host="h1")
    _seed(db_session, "cold-worker", host="h2")
    redis = _InMemoryRedis()
    _set_state(redis, "renamed-field", {"renamed_loaded": ["sft"]})
    _set_state(redis, "cold-worker", {"loaded": []})
    _set_queue(redis, "renamed-field", 0)
    _set_queue(redis, "cold-worker", 1)

    picked = _run(pick_worker(db_session, redis, "sft"))

    assert picked.id == "cold-worker"
    assert any(record.args == ("renamed-field",) for record in caplog.records)


# ── consume_task_stream ────────────────────────────────────────────


def _make_stream_client(events_or_exc) -> AsyncMock:
    if isinstance(events_or_exc, Exception):

        async def _aiter_text():  # noqa: D401
            raise events_or_exc
            yield ""  # pragma: no cover
    else:
        body = "".join(f"event: {t}\ndata: {json.dumps(d)}\n\n" for t, d in events_or_exc)

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


def _peer_dispatch_options(peer):
    return replace(_PEER_DISPATCH_OPTIONS, transport=peer.transport)


@pytest.mark.parametrize(
    ("consume", "payload", "expected"),
    [
        (
            consume_task_stream,
            {"error": "need 18.5 GB", "error_kind": "gpu_out_of_memory"},
            WorkerGpuOutOfMemory,
        ),
        (consume_task_stream, {"error": "CUDA out of memory"}, WorkerGenerationFailed),
        (
            consume_task_stream,
            {"error": "need 18.5 GB", "error_kind": None},
            WorkerGenerationFailed,
        ),
        (
            consume_task_stream,
            {"error": "CUDA out of memory", "error_kind": "unknown"},
            WorkerGenerationFailed,
        ),
        (consume_task_stream, {"error": "need 18.5 GB", "error_kind": 1}, WorkerGenerationFailed),
        (
            consume_task_stream,
            {"error": "CUDA out of memory", "error_kind": ""},
            WorkerGenerationFailed,
        ),
        (consume_task_stream, {"error_kind": "gpu_out_of_memory"}, WorkerProtocolError),
        (
            consume_task_stream,
            {"error": "", "error_kind": "gpu_out_of_memory"},
            WorkerProtocolError,
        ),
        (
            consume_download_task_stream,
            {"error": "need 18.5 GB", "error_kind": "gpu_out_of_memory"},
            WorkerTaskFailed,
        ),
    ],
    ids=[
        "typed",
        "absent",
        "null",
        "unknown",
        "integer",
        "empty-kind",
        "missing-error",
        "empty-error",
        "download",
    ],
)
def test_s8_worker_error_kind(consume, payload, expected):
    """S8-A/E: Only the generation wire kind selects GPU memory failure."""
    from typing import get_args

    from acestep_worker.models import TaskErrorKind

    assert WORKER_ERROR_GPU_OUT_OF_MEMORY in get_args(TaskErrorKind)
    body = "event: error\ndata: " + json.dumps(payload) + "\n\n"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=body))
    stream = consume(_make_picked(), "task-1", options=DispatchOptions(transport=transport))
    with pytest.raises(WorkerTaskFailed) as raised:
        _run(stream)
    assert type(raised.value) is expected


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
    operation = consume_task_stream(worker, "gen-1")
    with _patch_async_client(client):
        with pytest.raises(WorkerGenerationFailed) as exc_info:
            _run(operation)
    assert str(exc_info.value) == "GPU OOM"


def test_consume_task_stream_hands_on_each_phase_and_drops_an_event_missing_phase_or_progress(
    caplog: pytest.LogCaptureFixture,
) -> None:
    worker = _make_picked()
    captured: list[tuple[AceStepPhase, float]] = []

    async def on_progress(phase: AceStepPhase, fraction: float) -> None:
        captured.append((phase, fraction))

    events = [
        ("progress", {"progress": 0.2, "phase": "writing"}),
        ("progress", {"progress": 0.9, "phase": None}),
        ("progress", {"progress": 0.9, "phase": "unheard-of"}),
        ("progress", {"phase": "rendering"}),
        ("progress", {"progress": 0.5, "phase": "rendering"}),
        (
            "done",
            {
                "task_id": "g",
                "result": {"mode": "sft", "audio_path": "/x.wav", "seed": 1},
            },
        ),
    ]
    client = _make_stream_client(events)
    with _patch_async_client(client):
        _run(consume_task_stream(worker, "gen-1", on_progress=on_progress))

    assert captured == [(AceStepPhase.WRITING, 0.2), (AceStepPhase.RENDERING, 0.5)]
    assert sum(record.levelname == "WARNING" for record in caplog.records) == 3


def test_consume_task_stream_heartbeats_on_the_initial_stream_event() -> None:
    worker = _make_picked()
    heartbeats = 0

    def on_heartbeat() -> None:
        nonlocal heartbeats
        heartbeats += 1

    # TaskStore.subscribe() sends its current running snapshot first.
    events = [
        ("running", {"task_id": "gen-1"}),
        (
            "done",
            {
                "task_id": "gen-1",
                "result": {"mode": "sft", "audio_path": "/x.wav", "seed": 1},
            },
        ),
    ]
    client = _make_stream_client(events)
    with _patch_async_client(client):
        _run(consume_task_stream(worker, "gen-1", on_heartbeat=on_heartbeat))

    assert heartbeats == 2


def test_consume_task_stream_invalid_result_raises() -> None:
    worker = _make_picked()
    client = _make_stream_client([("done", {"task_id": "g", "result": {"mode": "sft"}})])
    operation = consume_task_stream(worker, "gen-1")
    with _patch_async_client(client):
        with pytest.raises(WorkerTaskFailed, match="invalid result"):
            _run(operation)


def test_consume_task_stream_done_missing_result_raises_protocol_error() -> None:
    worker = _make_picked()
    client = _make_stream_client([("done", {"task_id": "g"})])
    operation = consume_task_stream(worker, "gen-1")
    with _patch_async_client(client):
        with pytest.raises(WorkerProtocolError, match="missing 'result'"):
            _run(operation)


def test_consume_task_stream_error_missing_field_raises_protocol_error() -> None:
    worker = _make_picked()
    client = _make_stream_client([("error", {"task_id": "g"})])
    operation = consume_task_stream(worker, "gen-1")
    with _patch_async_client(client):
        with pytest.raises(WorkerProtocolError, match="missing 'error'"):
            _run(operation)


@pytest.mark.parametrize(
    "consume",
    [consume_task_stream, consume_download_task_stream],
    ids=["generation", "download"],
)
def test_consume_task_stream_empty_error_is_a_protocol_error_for_both_task_kinds(
    consume,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """defect:#1569: An empty 'error' field carries no cause, so it must not be relayed
    as one, for either task kind: the worker always sends text, and the job
    layer logs the cause and chooses the task-specific message. Download diverged here,
    raising ``WorkerTaskFailed('')`` instead — issue #227 unifies both
    consumers on the shared ``_consume_task_stream`` implementation."""
    worker = _make_picked()
    client = _make_stream_client([("error", {"error": ""})])
    operation = consume(worker, "task-1")
    with _patch_async_client(client):
        with caplog.at_level("WARNING", logger="songmaker_cli.scheduler"):
            with pytest.raises(WorkerProtocolError, match="empty 'error'"):
                _run(operation)
    assert any("empty 'error'" in r.message for r in caplog.records)


def test_consume_task_stream_reconnects_on_transport_drop(generation_worker_peer) -> None:
    """S5-D, L9: A dropped connection reconnects to the same real completed task."""

    async def exercise() -> None:
        scenario = WorkerScenario(stream_answers=(TransportFailure(httpx.ConnectError, "refused"),))
        async with generation_worker_peer(scenario) as peer:
            result = await dispatch_generation_on_worker(
                worker=_make_picked(loaded=[]),
                ace_config=_make_ace_config(),
                target_mode="sft",
                options=replace(
                    _PEER_DISPATCH_OPTIONS,
                    transport=peer.transport,
                    max_sse_reconnects=2,
                ),
            )
            assert Path(result.audio_path).is_file()
            assert [kind for kind, _ in peer.requests] == ["load", "submit", "stream", "stream"]

    _run(exercise())


def test_consume_task_stream_gives_up_after_max_reconnects(generation_worker_peer) -> None:
    """S5-A/D, L10: The transport boundary exhausts exactly the existing retry budget."""

    async def exercise() -> None:
        scenario = WorkerScenario(
            stream_answers=(TransportFailure(httpx.ConnectError, "refused"),) * 3,
        )
        async with generation_worker_peer(scenario) as peer:
            operation = consume_task_stream(
                _make_picked(),
                "gen-1",
                options=replace(
                    _PEER_DISPATCH_OPTIONS,
                    transport=peer.transport,
                    max_sse_reconnects=2,
                ),
            )
            with pytest.raises(WorkerGenerationUnavailable, match="refused"):
                await operation
            assert [kind for kind, _ in peer.requests] == ["stream"] * 3

    _run(exercise())


def test_consume_task_stream_fails_when_worker_stream_goes_silent(generation_worker_peer) -> None:
    """S5-A/D, L10: A read timeout is a stream failure without a reconnect."""

    async def exercise() -> None:
        scenario = WorkerScenario(
            stream_answers=(TransportFailure(httpx.ReadTimeout, "stream went silent"),),
        )
        async with generation_worker_peer(scenario) as peer:
            operation = consume_task_stream(
                _make_picked(),
                "gen-1",
                options=_peer_dispatch_options(peer),
            )
            with pytest.raises(WorkerGenerationUnavailable, match=WORKER_STREAM_WENT_SILENT):
                await operation
            assert [kind for kind, _ in peer.requests] == ["stream"]

    _run(exercise())


@pytest.mark.parametrize(
    ("transport_error", "expected_error", "message", "attempts"),
    [
        (httpx.ReadTimeout, WorkerTaskFailed, WORKER_STREAM_WENT_SILENT, 1),
        (httpx.ConnectError, httpx.ConnectError, "download lost", 3),
    ],
)
def test_s5_download_transport_contract(
    generation_worker_peer,
    transport_error,
    expected_error,
    message,
    attempts,
):
    """S5-D, L10: Downloads retain their own silence and exhausted-reconnect errors."""

    async def exercise():
        scenario = WorkerScenario(
            stream_answers=(TransportFailure(transport_error, "download lost"),) * attempts,
        )
        async with generation_worker_peer(scenario) as peer:
            operation = consume_download_task_stream(
                _make_picked(),
                "download",
                options=replace(
                    _PEER_DISPATCH_OPTIONS,
                    transport=peer.transport,
                    max_sse_reconnects=2,
                ),
            )
            with pytest.raises(expected_error, match=message) as raised:
                await operation
            assert type(raised.value) is expected_error
            assert peer.requests == [("stream", None)] * attempts

    _run(exercise())


def _make_ace_config():
    return AceStepConfig(prompt="x", lyrics="la la", audio_duration=60)


# ── DTO drift ──────────────────────────────────────────────────────


def test_dto_keys_match_worker_model_fields() -> None:
    from acestep_worker.models import GenerationTaskResult

    assert GenerationTaskResult.model_fields.keys() == GenerationTaskResultDTO.model_fields.keys()


# ── _ensure_loaded + _submit_generation (httpx unit tests) ─────────


def _record_into(announced: list[tuple[AceStepPhase, float]]):
    def on_progress(phase: AceStepPhase, fraction: float) -> None:
        announced.append((phase, fraction))

    return on_progress


def test_ensure_loaded_skips_when_already_loaded() -> None:
    worker = _make_picked(loaded=["sft"])
    announced: list[tuple[AceStepPhase, float]] = []
    with patch("songmaker_cli.scheduler.httpx.AsyncClient") as cls:
        from songmaker_cli.scheduler import _ensure_loaded

        _run(_ensure_loaded(worker, "sft", DispatchOptions(), _record_into(announced)))
    cls.assert_not_called()
    assert announced == []


def test_ensure_loaded_posts_when_missing() -> None:
    worker = _make_picked(loaded=[])
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    client = AsyncMock()
    client.post = AsyncMock(return_value=fake_response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    from songmaker_cli.scheduler import _ensure_loaded

    announced: list[tuple[AceStepPhase, float]] = []
    with patch("songmaker_cli.scheduler.httpx.AsyncClient", return_value=client):
        _run(_ensure_loaded(worker, "sft", DispatchOptions(), _record_into(announced)))

    assert announced == [(AceStepPhase.LOADING_MODEL, 0.0)]
    client.post.assert_called_once()
    args, kwargs = client.post.call_args
    assert args[0].endswith("/load_model")
    assert kwargs["json"] == {"mode": "sft"}


def test_later_takes_of_a_cold_job_neither_reload_nor_announce_loading(
    generation_worker_peer,
) -> None:
    """S5-D, L3/L9: Later takes reuse the loaded model over the real worker protocol."""
    admitted_cold = _make_picked(loaded=[])
    phases_per_take: list[list[AceStepPhase]] = []

    async def run_job() -> None:
        async with generation_worker_peer() as peer:
            for _ in range(3):
                phases: list[AceStepPhase] = []
                phases_per_take.append(phases)
                result = await dispatch_generation_on_worker(
                    worker=admitted_cold,
                    ace_config=_make_ace_config(),
                    target_mode="sft",
                    on_progress=lambda phase, _fraction, phases=phases: phases.append(phase),
                    options=_peer_dispatch_options(peer),
                )
                assert Path(result.audio_path).is_file()
            assert [mode for kind, mode in peer.requests if kind == "load"] == ["sft"]

    _run(run_job())
    assert [phases.count(AceStepPhase.LOADING_MODEL) for phases in phases_per_take] == [1, 0, 0]


def test_a_take_whose_mode_another_job_evicted_reloads_it_once_and_succeeds(
    generation_worker_peer,
) -> None:
    """S5-D, L3/L9: A real one-model cache evicts and the next take reloads once."""
    sft_job_view = _make_picked(loaded=[])
    turbo_job_view = _make_picked(loaded=[])
    sft_phases_per_take: list[list[AceStepPhase]] = []

    async def run_two_jobs_whose_takes_alternate() -> None:
        async with generation_worker_peer() as peer:
            for _ in range(2):
                sft_phases_per_take.append([])
                for view, mode, phases in (
                    (sft_job_view, "sft", sft_phases_per_take[-1]),
                    (turbo_job_view, "turbo", []),
                ):
                    result = await dispatch_generation_on_worker(
                        worker=view,
                        ace_config=_make_ace_config(),
                        target_mode=mode,
                        on_progress=lambda phase, _fraction, phases=phases: phases.append(phase),
                        options=_peer_dispatch_options(peer),
                    )
                    assert Path(result.audio_path).is_file()
            assert [mode for kind, mode in peer.requests if kind == "load"] == [
                "sft",
                "turbo",
                "sft",
                "turbo",
            ]

    _run(run_two_jobs_whose_takes_alternate())
    assert [phases.count(AceStepPhase.LOADING_MODEL) for phases in sft_phases_per_take] == [1, 1]


@pytest.mark.parametrize(
    "error_type",
    [httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout],
)
def test_generation_worker_peer_replays_transport_answers(generation_worker_peer, error_type):
    """S5-A/D, L3/L9: The shared transport scripts failures and survives client exits."""

    async def exercise():
        failure = TransportFailure(error_type, "peer transport failure")
        recovered = WorkerReply(200, "recovered")
        scenario = WorkerScenario(
            load_answers=(failure, recovered),
            submit_answers=(failure, recovered),
            stream_answers=(failure, recovered),
        )
        async with generation_worker_peer(scenario) as peer:
            for path in ("/load_model", "/generate", "/tasks/t1/stream"):
                for fails in (True, False):
                    async with httpx.AsyncClient(transport=peer.transport) as client:
                        if fails:
                            with pytest.raises(error_type, match="peer transport failure"):
                                await client.get("http://worker" + path)
                        else:
                            response = await client.get("http://worker" + path)
                            assert response.text == "recovered"
        async with httpx.AsyncClient(transport=peer.transport) as client:
            with pytest.raises(RuntimeError, match="Worker peer is closed"):
                await client.get("http://worker/load_model")
        assert not peer.deps.heartbeat.is_running

    _run(exercise())


@pytest.mark.parametrize(
    "error_type", [httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout]
)
@pytest.mark.parametrize("reload", [False, True], ids=["initial", "reload"])
def test_s5_load_transport_failure_before_response(generation_worker_peer, error_type, reload):
    """S5-A/B, L3/L6/L10: Load transport causes survive, without another load attempt."""

    async def exercise():
        scenario = WorkerScenario(load_answers=(TransportFailure(error_type, "load lost"),))
        async with generation_worker_peer(scenario) as peer:
            operation = dispatch_generation_on_worker(
                worker=_make_picked(loaded=["sft"] if reload else []),
                ace_config=_make_ace_config(),
                target_mode="sft",
                options=_peer_dispatch_options(peer),
            )
            with pytest.raises(WorkerGenerationUnavailable, match="load lost") as raised:
                await operation
            assert type(raised.value.__cause__) is error_type
            assert peer.requests == ([("submit", "sft")] if reload else []) + [("load", "sft")]

    _run(exercise())


@pytest.mark.parametrize(
    "error_type", [httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout]
)
@pytest.mark.parametrize("reload", [False, True], ids=["initial", "reload"])
def test_s5_submit_transport_failure_before_response(generation_worker_peer, error_type, reload):
    """S5-A/B, L6/L9/L10: Submit transport failures never resubmit an uncertain request."""

    async def exercise():
        failure = TransportFailure(error_type, "submit lost")
        scenario = WorkerScenario(
            loaded_modes=() if reload else ("sft",),
            submit_answers=(None, failure) if reload else (failure,),
        )
        async with generation_worker_peer(scenario) as peer:
            operation = dispatch_generation_on_worker(
                worker=_make_picked(loaded=["sft"]),
                ace_config=_make_ace_config(),
                target_mode="sft",
                options=_peer_dispatch_options(peer),
            )
            with pytest.raises(WorkerGenerationUnavailable, match="submit lost") as raised:
                await operation
            assert type(raised.value.__cause__) is error_type
            assert peer.requests == ([("submit", "sft"), ("load", "sft")] if reload else []) + [
                ("submit", "sft")
            ]

    _run(exercise())


@pytest.mark.parametrize("load_fails", [False, True], ids=["still-missing", "reload-failed"])
def test_s5_mode_still_missing_after_reload(generation_worker_peer, load_fails):
    """S5-A/B, L3/L10: Exactly one reload precedes final typed unavailability."""

    async def exercise():
        missing = WorkerReply(409, MODE_NOT_LOADED_DETAIL.format(mode="sft"))
        scenario = WorkerScenario(
            submit_answers=(missing, missing),
            load_answers=(WorkerReply(503, "load failed"),) if load_fails else (),
        )
        async with generation_worker_peer(scenario) as peer:
            operation = dispatch_generation_on_worker(
                worker=_make_picked(loaded=["sft"]),
                ace_config=_make_ace_config(),
                target_mode="sft",
                options=_peer_dispatch_options(peer),
            )
            with pytest.raises(WorkerGenerationUnavailable) as raised:
                await operation
            expected_cause = httpx.HTTPStatusError if load_fails else WorkerModeNotLoaded
            assert isinstance(raised.value.__cause__, expected_cause)
            assert peer.requests == [("submit", "sft"), ("load", "sft")] + (
                [] if load_fails else [("submit", "sft")]
            )

    _run(exercise())


@pytest.mark.parametrize("stop_early", [False, True], ids=["normal", "stopped-worker"])
def test_generation_worker_peer_releases_resources(generation_worker_peer, db_factory, stop_early):
    """S5-D, L9/L10: Normal and deliberately stopped workers release tasks and sockets."""

    async def exercise():
        async with generation_worker_peer(db_factory=db_factory) as peer:
            address = peer.http_server.socket.getsockname()
            worker = await admit_generation_worker(
                target_mode="sft",
                redis=peer.redis,
                db_factory=db_factory,
            )
            result = await dispatch_generation_on_worker(
                worker=worker,
                ace_config=_make_ace_config(),
                target_mode="sft",
                options=replace(
                    _PEER_DISPATCH_OPTIONS,
                    sse_read_timeout_seconds=_SOCKET_SSE_READ_TIMEOUT_SECONDS,
                ),
            )
            assert Path(result.audio_path).is_file()
            if stop_early:
                await peer.stop_server()
        assert not peer.deps.heartbeat.is_running
        assert peer.deps.cache.loaded_modes() == []
        assert all(task.done() for task in peer.generation_tasks)
        assert peer.http_server.server_task.done()
        with socket.socket() as reused:
            reused.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            reused.bind(address)

    _run(exercise())


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
        task_id = _run(
            _submit_generation(
                worker,
                _make_ace_config(),
                "sft",
                DispatchOptions(),
            )
        )
    assert task_id == "gen-1"
    args, kwargs = client.post.call_args
    assert args[0].endswith("/generate")
    assert kwargs["json"] == {"mode": "sft", "config": asdict(_make_ace_config())}


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
    good_client = _make_stream_client(
        [
            ("done", {"task_id": "t", "result": {"mode": "sft", "size_bytes": 1}}),
        ]
    )
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

    operation = collect()
    with pytest.raises(httpx.ConnectError):
        _run(operation)


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
    operation = pick_any_online_worker(db_session, redis)
    with pytest.raises(NoCapacityError):
        _run(operation)


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
    operation = consume_download_task_stream(worker, "d")
    with _patch_async_client(client):
        with pytest.raises(WorkerTaskFailed, match="HF 401"):
            _run(operation)


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
    operation = consume_download_task_stream(worker, "d")
    with _patch_async_client(client):
        with pytest.raises(WorkerTaskFailed, match="invalid download result"):
            _run(operation)


def test_consume_download_task_stream_done_missing_result_raises_protocol_error() -> None:
    worker = _make_picked()
    client = _make_stream_client([("done", {"task_id": "d"})])
    operation = consume_download_task_stream(worker, "d")
    with _patch_async_client(client):
        with pytest.raises(WorkerProtocolError, match="missing 'result'"):
            _run(operation)


def test_consume_download_task_stream_error_missing_field_raises_protocol_error() -> None:
    worker = _make_picked()
    client = _make_stream_client([("error", {"task_id": "d"})])
    operation = consume_download_task_stream(worker, "d")
    with _patch_async_client(client):
        with pytest.raises(WorkerProtocolError, match="missing 'error'"):
            _run(operation)


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
    operation = consume_download_task_stream(worker, "d")
    with _patch_async_client(client):
        with pytest.raises(WorkerTaskFailed, match="ended without"):
            _run(operation)


def test_generation_worker_peer_rejects_socket_transport_failures(
    generation_worker_peer,
    db_factory,
):
    """S5-A/D: A transport script cannot silently become an HTTP 500."""

    async def exercise():
        scenario = WorkerScenario(
            load_answers=(TransportFailure(httpx.ConnectError, "unreachable"),),
        )
        peer_context = generation_worker_peer(scenario, db_factory=db_factory)

        async def enter_socket_peer():
            async with peer_context:
                pytest.fail("Invalid socket scenario was accepted")

        operation = enter_socket_peer()
        with pytest.raises(ValueError, match="TransportFailure requires the ASGI transport"):
            await operation

    _run(exercise())
