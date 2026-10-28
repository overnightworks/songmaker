from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import fakeredis
import fakeredis.aioredis
import httpx
import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from uvicorn.main import STARTUP_FAILURE

from acestep_worker.__main__ import serve
from acestep_worker.heartbeat import HeartbeatLoop
from acestep_worker.lm_failure import LM_FAILURE_EXIT_CODE, lm_failure_key
from acestep_worker.model_cache import CapacityError, LoadedModel, ModelCache, UnknownModeError
from acestep_worker.subprocess_runner import LmInitFailedError, SubprocessStartError
from acestep_worker.task_store import TaskStore
from acestep_worker.wrapper import WorkerDeps, build_state_payload, create_app

_HEADERS = {"X-Internal-Token": "test-internal-token"}
_WORKER_ID = "acestep-worker-0"
_TAIL = "ValueError: LM weights missing"
_STOP_WITHIN_SECONDS = 5
_NOT_STOPPED_EXIT_CODE = 99

Loader = Callable[[str], Awaitable[LoadedModel]]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class _Worker:
    def __init__(self, tmp_path: Path) -> None:
        self._server = fakeredis.FakeServer()
        self.redis = fakeredis.aioredis.FakeRedis(server=self._server)
        self.loader: Loader = self._load_ok
        self.loaded_modes: list[str] = []
        self.shutdown_requests: list[int] = []
        cache = ModelCache(
            vram_budget_gb=24.0,
            model_sizes={"sft": 6.0, "turbo": 6.0, "xl-sft": 30.0},
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
            request_shutdown=self._record_shutdown_request,
        )
        self.deps.heartbeat = HeartbeatLoop(
            redis=self.redis,
            worker_id=_WORKER_ID,
            state_provider=lambda: build_state_payload(self.deps),
        )

    def _record_shutdown_request(self, exit_code: int) -> None:
        self.shutdown_requests.append(exit_code)

    async def _load_ok(self, mode: str) -> LoadedModel:
        self.loaded_modes.append(mode)
        return LoadedModel(mode=mode, handle=f"handle-{mode}", port=8101)

    async def _load_through(self, mode: str) -> LoadedModel:
        return await self.loader(mode)

    async def _unload(self, _: LoadedModel) -> None:
        return None

    def client(self) -> TestClient:
        return TestClient(create_app(self.deps), headers=_HEADERS)

    def serve_until_it_stops(
        self,
        request: Callable[[httpx.Client], object],
        **serve_options: Any,
    ) -> int:
        """Run the real server; `request` runs once it answers and returns the exit code owed.

        A server that is still up `_STOP_WITHIN_SECONDS` after the request is stopped with
        `_NOT_STOPPED_EXIT_CODE`, so a missing shutdown fails the test instead of hanging it.
        The forced exit never ends the test process unless a test passes its own.
        """
        serve_options.setdefault("force_exit", lambda _: None)
        port = _free_port()
        deps = self.deps
        outcome: list[object] = []
        served = threading.Event()

        def drive() -> None:
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers=_HEADERS) as client:
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline and not served.is_set():
                        try:
                            client.get("/health")
                            break
                        except httpx.TransportError:
                            time.sleep(0.05)
                    outcome.append(request(client))
            finally:
                if not served.wait(_STOP_WITHIN_SECONDS):
                    deps.request_shutdown(_NOT_STOPPED_EXIT_CODE)

        driver = threading.Thread(target=drive)
        driver.start()
        try:
            exit_code = serve(deps, "127.0.0.1", port, **serve_options)
        finally:
            served.set()
            driver.join(timeout=10)
        self.driven = outcome
        return exit_code

    def redis_is_down(self, down: bool) -> None:
        self._server.connected = not down

    def key(self) -> bytes | None:
        return asyncio.run(self._inspector_call("get"))

    def plant_key(self, mode: str) -> None:
        asyncio.run(self._inspector_call("set", mode))

    async def _inspector_call(self, operation: str, *arguments: str):
        # The app's connection is bound to the test client's event loop.
        inspector = fakeredis.aioredis.FakeRedis(server=self._server)
        return await getattr(inspector, operation)(lm_failure_key(_WORKER_ID), *arguments)


@pytest.fixture
def worker(tmp_path: Path) -> _Worker:
    return _Worker(tmp_path)


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
        loaded = client.get("/loaded_models").json()["loaded"]

    assert response.status_code == 502
    assert _TAIL in response.json()["detail"]
    assert loaded == []
    assert worker.key() == b"sft"
    assert worker.shutdown_requests == [LM_FAILURE_EXIT_CODE]


def test_worker_still_leaves_when_the_key_cannot_be_written(worker: _Worker) -> None:
    _fail_the_lm(worker)

    with worker.client() as client:
        worker.redis_is_down(True)
        response = client.post("/load_model", json={"mode": "sft"})
        worker.redis_is_down(False)

    assert response.status_code == 502
    assert worker.shutdown_requests == [LM_FAILURE_EXIT_CODE]


def test_lm_failure_leaves_the_other_loaded_models_to_the_shutdown(worker: _Worker) -> None:
    async def fail_only_turbo(mode: str) -> LoadedModel:
        if mode == "turbo":
            raise LmInitFailedError(_TAIL)
        return await worker._load_ok(mode)

    worker.loader = fail_only_turbo

    with worker.client() as client:
        client.post("/load_model", json={"mode": "sft"})
        loaded_before = client.get("/loaded_models").json()["loaded"]
        client.post("/load_model", json={"mode": "turbo"})
        loaded_after = client.get("/loaded_models").json()["loaded"]

    assert [model["mode"] for model in loaded_before] == ["sft"]
    assert [model["mode"] for model in loaded_after] == ["sft"]


def test_load_that_fails_for_another_reason_keeps_the_worker_and_writes_no_key(
    worker: _Worker,
) -> None:
    worker.loader = _raise(SubprocessStartError("uv not found"))

    with worker.client() as client:
        response = client.post("/load_model", json={"mode": "sft"})

    assert response.status_code == 502
    assert worker.key() is None
    assert worker.shutdown_requests == []


def test_load_with_an_initialised_lm_writes_no_key_and_keeps_the_worker(worker: _Worker) -> None:
    with worker.client() as client:
        response = client.post("/load_model", json={"mode": "sft"})

    assert response.status_code == 200
    assert worker.key() is None
    assert worker.shutdown_requests == []


def _timer_threads() -> set[threading.Thread]:
    return {thread for thread in threading.enumerate() if isinstance(thread, threading.Timer)}


def test_served_worker_exits_75_after_an_lm_failure_and_answers_the_load_first(
    worker: _Worker,
) -> None:
    _fail_the_lm(worker)
    timers_before = _timer_threads()

    exit_code = worker.serve_until_it_stops(
        lambda client: client.post("/load_model", json={"mode": "sft"}).status_code
    )
    watchdogs = _timer_threads() - timers_before
    for watchdog in watchdogs:
        watchdog.join(timeout=1)

    assert exit_code == LM_FAILURE_EXIT_CODE
    assert worker.driven == [502]
    assert worker.key() == b"sft"
    assert not [watchdog for watchdog in watchdogs if watchdog.is_alive()]


def test_served_worker_with_a_failing_retry_exits_with_uvicorns_startup_failure(
    worker: _Worker,
) -> None:
    worker.plant_key("sft")
    _fail_the_lm(worker)

    exit_code = worker.serve_until_it_stops(lambda client: None)

    assert exit_code == STARTUP_FAILURE
    assert worker.key() == b"sft"


def test_served_worker_is_forced_out_when_a_running_take_holds_the_shutdown(
    worker: _Worker,
) -> None:
    take_still_polling = threading.Event()
    forced_exits: list[int] = []

    async def fail_while_a_take_polls(_: str) -> LoadedModel:
        asyncio.get_running_loop().run_in_executor(None, take_still_polling.wait, 30)
        raise LmInitFailedError(_TAIL)

    def force_exit(exit_code: int) -> None:
        forced_exits.append(exit_code)
        take_still_polling.set()

    worker.loader = fail_while_a_take_polls

    worker.serve_until_it_stops(
        lambda client: client.post("/load_model", json={"mode": "sft"}),
        force_exit=force_exit,
        forced_exit_seconds=0.5,
    )

    assert forced_exits == [LM_FAILURE_EXIT_CODE]


def test_start_without_the_key_loads_nothing(worker: _Worker) -> None:
    with worker.client():
        pass

    assert worker.loaded_modes == []
    assert worker.deps.registration_task is not None


def test_start_with_the_key_loads_the_failed_mode_clears_the_key_and_then_registers(
    worker: _Worker,
) -> None:
    worker.plant_key("sft")

    with worker.client():
        assert worker.deps.heartbeat.is_running
        assert worker.deps.registration_task is not None

    assert worker.loaded_modes == ["sft"]
    assert worker.key() is None


def test_retry_that_fails_on_the_lm_fails_the_start_and_keeps_the_key(worker: _Worker) -> None:
    worker.plant_key("sft")
    _fail_the_lm(worker)

    with pytest.raises(LmInitFailedError), worker.client():
        pass

    assert worker.key() == b"sft"
    assert worker.deps.registration_task is None
    assert not worker.deps.heartbeat.is_running


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(SubprocessStartError("checkpoint deleted"), id="start-error"),
        pytest.param(CapacityError("no room"), id="capacity"),
        pytest.param(UnknownModeError("sft"), id="unknown-mode"),
        pytest.param(FileNotFoundError("checkpoint dir"), id="process-start-os-error"),
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


def test_start_fails_as_before_when_redis_is_down(worker: _Worker) -> None:
    worker.redis_is_down(True)

    with pytest.raises(RedisConnectionError), worker.client():
        pass
