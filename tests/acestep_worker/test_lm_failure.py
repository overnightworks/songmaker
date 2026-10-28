from __future__ import annotations

import asyncio
import signal
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from acestep_worker.lm_failure import LM_FAILURE_EXIT_CODE, lm_failure_key
from acestep_worker.model_cache import CapacityError, LoadedModel, ModelCache, UnknownModeError
from acestep_worker.subprocess_runner import LmInitFailedError, SubprocessStartError
from acestep_worker.task_store import TaskStore
from acestep_worker.wrapper import WorkerDeps, build_state_payload, create_app

from acestep_worker.heartbeat import HeartbeatLoop

_HEADERS = {"X-Internal-Token": "test-internal-token"}
_WORKER_ID = "acestep-worker-0"
_TAIL = "ValueError: LM weights missing"

Loader = Callable[[str], Awaitable[LoadedModel]]


class _Worker:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._server = fakeredis.FakeServer()
        self.redis = fakeredis.aioredis.FakeRedis(server=self._server)
        self.loader: Loader = self._load_ok
        self.loaded_modes: list[str] = []
        self.kills: list[tuple[int, int]] = []
        self._killed = threading.Event()
        monkeypatch.setattr("acestep_worker.lm_failure.os.kill", self._record_kill)
        monkeypatch.setattr("acestep_worker.lm_failure.EXIT_DELAY_SECONDS", 0)
        cache = ModelCache(
            vram_budget_gb=24.0,
            model_sizes={"sft": 6.0, "xl-sft": 30.0},
            loader=self._load_through,
            unloader=self._unload,
        )
        self.deps = WorkerDeps(
            worker_id=_WORKER_ID,
            cache=cache,
            task_store=TaskStore(),
            heartbeat=None,  # type: ignore[arg-type]
            redis=self.redis,
            registry_client=None,
            registration=None,
            checkpoint_dir=tmp_path,
            audio_output_dir=tmp_path / "audio",
            internal_token="test-internal-token",
            generate_runner=None,
        )
        self.deps.heartbeat = HeartbeatLoop(
            redis=self.redis,
            worker_id=_WORKER_ID,
            state_provider=lambda: build_state_payload(self.deps),
        )

    def _record_kill(self, pid: int, sig: int) -> None:
        self.kills.append((pid, sig))
        self._killed.set()

    async def _load_ok(self, mode: str) -> LoadedModel:
        self.loaded_modes.append(mode)
        return LoadedModel(mode=mode, handle=f"handle-{mode}", port=8101)

    async def _load_through(self, mode: str) -> LoadedModel:
        return await self.loader(mode)

    async def _unload(self, _: LoadedModel) -> None:
        return None

    def client(self) -> TestClient:
        return TestClient(create_app(self.deps), headers=_HEADERS)

    def wait_for_sigterm(self) -> None:
        assert self._killed.wait(timeout=5)

    def key(self) -> bytes | None:
        return asyncio.run(self._inspector_call("get"))

    def plant_key(self, mode: str) -> None:
        asyncio.run(self._inspector_call("set", mode))

    async def _inspector_call(self, operation: str, *arguments: str):
        # The app's connection is bound to the test client's event loop.
        inspector = fakeredis.aioredis.FakeRedis(server=self._server)
        return await getattr(inspector, operation)(lm_failure_key(_WORKER_ID), *arguments)


@pytest.fixture
def worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Worker:
    return _Worker(tmp_path, monkeypatch)


def _raise(error: Exception) -> Loader:
    async def loader(_: str) -> LoadedModel:
        raise error

    return loader


def _fail_the_lm(worker: _Worker) -> None:
    worker.loader = _raise(LmInitFailedError(_TAIL))


def test_load_without_the_lm_answers_502_remembers_the_mode_and_ends_the_worker(
    worker: _Worker,
) -> None:
    _fail_the_lm(worker)

    with worker.client() as client:
        response = client.post("/load_model", json={"mode": "sft"})
        worker.wait_for_sigterm()
        loaded = client.get("/loaded_models").json()["loaded"]

    assert response.status_code == 502
    assert _TAIL in response.json()["detail"]
    assert loaded == []
    assert worker.key() == b"sft"
    assert worker.kills[0][1] == signal.SIGTERM
    assert worker.deps.exit_code == LM_FAILURE_EXIT_CODE


def test_exit_code_is_none_of_the_codes_the_worker_already_uses() -> None:
    assert LM_FAILURE_EXIT_CODE not in {0, 1, 2, 3}


def test_worker_still_leaves_when_the_key_cannot_be_written(
    worker: _Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_the_lm(worker)

    async def broken_set(*_args: object, **_kwargs: object) -> None:
        raise ConnectionError("redis down")

    monkeypatch.setattr(worker.redis, "set", broken_set)

    with worker.client() as client:
        response = client.post("/load_model", json={"mode": "sft"})
        worker.wait_for_sigterm()

    assert response.status_code == 502
    assert worker.deps.exit_code == LM_FAILURE_EXIT_CODE


def test_load_that_fails_for_another_reason_keeps_the_worker_and_writes_no_key(
    worker: _Worker,
) -> None:
    worker.loader = _raise(SubprocessStartError("uv not found"))

    with worker.client() as client:
        response = client.post("/load_model", json={"mode": "sft"})

    assert response.status_code == 502
    assert worker.key() is None
    assert worker.deps.exit_code == 0
    assert worker.kills == []


def test_load_with_an_initialised_lm_writes_no_key_and_keeps_the_worker(worker: _Worker) -> None:
    with worker.client() as client:
        response = client.post("/load_model", json={"mode": "sft"})

    assert response.status_code == 200
    assert worker.key() is None
    assert worker.deps.exit_code == 0
    assert worker.kills == []


def test_manual_restart_exits_cleanly_and_writes_no_key(worker: _Worker) -> None:
    with worker.client() as client:
        response = client.post("/restart")
        worker.wait_for_sigterm()

    assert response.status_code == 200
    assert worker.key() is None
    assert worker.deps.exit_code == 0


def test_start_without_the_key_loads_nothing(worker: _Worker) -> None:
    with worker.client():
        pass

    assert worker.loaded_modes == []
    assert worker.deps.registration_task is not None


def test_start_with_the_key_loads_the_failed_mode_clears_the_key_and_then_registers(
    worker: _Worker,
) -> None:
    worker.plant_key("sft")

    with worker.client() as client:
        assert worker.deps.heartbeat.is_running
        assert worker.deps.registration_task is not None

    assert worker.loaded_modes == ["sft"]
    assert worker.key() is None


def test_retry_that_fails_on_the_lm_fails_the_start_and_keeps_the_key(worker: _Worker) -> None:
    worker.plant_key("sft")
    _fail_the_lm(worker)

    with pytest.raises(LmInitFailedError):
        worker.client().__enter__()

    assert worker.key() == b"sft"
    assert worker.deps.registration_task is None
    assert not worker.deps.heartbeat.is_running


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(SubprocessStartError("checkpoint deleted"), id="start-error"),
        pytest.param(CapacityError("no room"), id="capacity"),
        pytest.param(UnknownModeError("sft"), id="unknown-mode"),
    ],
)
def test_retry_that_fails_otherwise_clears_the_key_and_starts_empty(
    worker: _Worker, failure: Exception
) -> None:
    worker.plant_key("sft")
    worker.loader = _raise(failure)

    with worker.client() as client:
        loaded = client.get("/loaded_models").json()["loaded"]
        assert worker.deps.heartbeat.is_running

    assert loaded == []
    assert worker.key() is None
    assert worker.deps.last_error is not None


def test_start_fails_as_before_when_redis_is_down(
    worker: _Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken_get(*_args: object, **_kwargs: object) -> None:
        raise ConnectionError("redis down")

    monkeypatch.setattr(worker.redis, "get", broken_get)

    with pytest.raises(ConnectionError):
        worker.client().__enter__()
