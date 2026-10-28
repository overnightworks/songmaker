"""One configurable HTTP/SSE peer for generation jobs and scheduler proofs."""

from __future__ import annotations

import asyncio
import json
import socket
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import fakeredis.aioredis
import httpx
import pytest
import uvicorn
from e2e_fixtures.fake_training_worker import (
    FakeTrainingWorkerSettings,
    build_fake_worker_deps,
)
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from acestep_worker.model_cache import LoadedModel, ModelCache
from acestep_worker.wrapper import create_app
from songmaker_cli.db.queries.workers import register_worker
from songmaker_cli.settings import get_settings

PEER_DEADLINE_SECONDS = 15
PEER_CLEANUP_DEADLINE_SECONDS = 3


@dataclass(frozen=True)
class WorkerReply:
    status: int
    body: str
    media_type: str = "text/plain"


@dataclass(frozen=True)
class WorkerStream:
    events: tuple[tuple[str, dict], ...]
    release: asyncio.Event | None = None
    entered: asyncio.Event | None = None

    def response(self) -> Response:
        return Response(
            "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in self.events),
            media_type="text/event-stream",
        )


@dataclass(frozen=True)
class TransportFailure:
    error: type[httpx.TransportError]
    message: str


WorkerAnswer = WorkerReply | WorkerStream | TransportFailure | None


@dataclass(frozen=True)
class WorkerScenario:
    loaded_modes: tuple[str, ...] = ()
    load_answers: tuple[WorkerAnswer, ...] = ()
    submit_answers: tuple[WorkerAnswer, ...] = ()
    stream_answers: tuple[WorkerAnswer, ...] = ()
    model_loader: Callable[[str], Awaitable[LoadedModel]] | None = None


class BorrowedWorkerTransport(httpx.AsyncBaseTransport):
    """Clients borrow the transport; the peer owns its lifetime."""

    def __init__(self, transport: httpx.ASGITransport) -> None:
        self.transport = transport
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.closed:
            raise RuntimeError("Worker peer is closed")
        return await self.transport.handle_async_request(request)

    async def aclose(self) -> None:
        # AsyncClient exits do not own the shared scenario.
        return

    async def close_owner(self) -> None:
        self.closed = True
        await self.transport.aclose()


class ReadyWorkerServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config) -> None:
        super().__init__(config)
        self.ready = asyncio.Event()

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets)
        self.ready.set()


class LoopbackServer:
    """Own one HTTP server and its socket; callers bound the proof and cleanup."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.server: ReadyWorkerServer | None = None
        self.server_task: asyncio.Task | None = None
        self.socket: socket.socket | None = None

    async def start(self) -> str:
        self.socket = socket.socket()
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen()
        self.socket.setblocking(False)
        port = self.socket.getsockname()[1]
        self.server = ReadyWorkerServer(
            uvicorn.Config(
                self.app,
                host="127.0.0.1",
                port=port,
                lifespan="off",
                log_config=None,
                access_log=False,
                timeout_graceful_shutdown=1,
            )
        )
        self.server_task = asyncio.create_task(self.server.serve(sockets=[self.socket]))
        ready_task = asyncio.create_task(self.server.ready.wait())
        try:
            done, _ = await asyncio.wait(
                (ready_task, self.server_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if self.server_task in done:
                await self.server_task
                raise RuntimeError("HTTP server stopped before readiness")
        finally:
            ready_task.cancel()
            await asyncio.gather(ready_task, return_exceptions=True)
        return f"http://127.0.0.1:{port}"

    async def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
        try:
            if self.server_task is not None:
                await self.server_task
        finally:
            if self.socket is not None:
                self.socket.close()


async def load_peer_model(mode: str) -> LoadedModel:
    return LoadedModel(mode=mode, handle=object(), port=0)


async def unload_peer_model(model: LoadedModel) -> None:
    del model


class GenerationWorkerPeer:
    def __init__(self, tmp_path: Path, scenario: WorkerScenario) -> None:
        self.phase = "startup"
        self.redis = fakeredis.aioredis.FakeRedis()
        self.audio_dir = tmp_path / "audio"
        self.data_dir = tmp_path / "data"
        self.data_dir.mkdir(exist_ok=True)
        self.settings = FakeTrainingWorkerSettings(
            redis_url="redis://unused",
            internal_token=get_settings().songmaker_internal_token.get_secret_value(),
            audio_dir=self.audio_dir,
            control_plane_url="",
            worker_id="generation-test-worker",
            worker_host="127.0.0.1",
        )
        self.deps = build_fake_worker_deps(self.settings, redis=self.redis)
        # The real cache supplies the one-model eviction behaviour for alternating jobs.
        self.deps.cache = ModelCache(
            vram_budget_gb=1.0,
            model_sizes={"sft": 1.0, "turbo": 1.0},
            loader=scenario.model_loader or load_peer_model,
            unloader=unload_peer_model,
        )
        self.generation_tasks: set[asyncio.Task] = set()
        self.generation_started = asyncio.Event()
        original_runner = self.deps.generate_runner

        async def run_generation(*args, **kwargs):
            task = asyncio.current_task()
            assert task is not None
            self.generation_tasks.add(task)
            self.generation_started.set()
            await original_runner(*args, **kwargs)

        self.deps.generate_runner = run_generation
        self.worker_app = create_app(self.deps)
        self.answers = {
            "load": deque(scenario.load_answers),
            "submit": deque(scenario.submit_answers),
            "stream": deque(scenario.stream_answers),
        }
        self.requests: list[tuple[str, str | None]] = []
        self.http_server = LoopbackServer(self)
        self.transport_owner = httpx.ASGITransport(app=self)
        self.transport = BorrowedWorkerTransport(self.transport_owner)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope["path"]
        kind = {"/load_model": "load", "/generate": "submit"}.get(path)
        if path.endswith("/stream"):
            kind = "stream"
        if kind is None:
            await self.worker_app(scope, receive, send)
            return
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        mode = json.loads(body).get("mode") if body else None
        self.requests.append((kind, mode))
        answer = self.answers[kind].popleft() if self.answers[kind] else None
        if isinstance(answer, TransportFailure):
            raise answer.error(answer.message)
        if isinstance(answer, WorkerReply):
            await Response(answer.body, answer.status, media_type=answer.media_type)(
                scope,
                receive,
                send,
            )
        elif isinstance(answer, WorkerStream):
            if answer.entered is not None:
                answer.entered.set()
            if answer.release is not None:
                await answer.release.wait()
            await answer.response()(scope, receive, send)
        else:
            replayed = False

            async def replay_body():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            status = None

            async def observe_response(message):
                nonlocal status
                if message["type"] == "http.response.start":
                    status = message["status"]
                await send(message)

            if kind == "submit":
                self.generation_started.clear()
            await self.worker_app(scope, replay_body, observe_response)
            if kind == "submit" and status == 200:
                previous_phase = self.phase
                self.phase = "generation startup"
                await self.generation_started.wait()
                self.phase = previous_phase

    async def start_server(self, db_factory) -> None:
        if any(
            isinstance(answer, TransportFailure)
            for answers in self.answers.values()
            for answer in answers
        ):
            raise ValueError("TransportFailure requires the ASGI transport, not a real server")
        self.phase = "server readiness"
        await self.http_server.start()
        port = self.http_server.socket.getsockname()[1]
        with db_factory() as session:
            register_worker(
                session,
                worker_id=self.settings.worker_id,
                host="127.0.0.1",
                port=port,
                gpu_id=None,
                vram_total_gb=1.0,
            )
            session.commit()
        await self.deps.heartbeat.publish_once()

    async def stop_generation_tasks(self) -> None:
        for task in self.generation_tasks:
            if not task.done():
                task.cancel()
        results = await asyncio.gather(*self.generation_tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                raise result

    async def stop_server(self) -> None:
        await self.http_server.stop()


@asynccontextmanager
async def open_generation_worker_peer(
    tmp_path: Path,
    scenario: WorkerScenario = WorkerScenario(),
    *,
    db_factory=None,
    deadline_seconds: float = PEER_DEADLINE_SECONDS,
    startup_deadline_seconds: float = PEER_DEADLINE_SECONDS,
) -> AsyncIterator[GenerationWorkerPeer]:
    peer = GenerationWorkerPeer(tmp_path, scenario)
    stack = AsyncExitStack()
    stalled_phase = None

    async def cleanup(phase, callback, *args):
        nonlocal stalled_phase
        peer.phase = phase
        deadline = asyncio.timeout(PEER_CLEANUP_DEADLINE_SECONDS)
        try:
            async with deadline:
                await callback(*args)
        except asyncio.CancelledError:
            stalled_phase = phase
            raise
        except TimeoutError as exc:
            if deadline.expired():
                raise TimeoutError(f"Worker peer timed out during {phase}") from exc
            raise

    stack.push_async_callback(cleanup, "Redis shutdown", peer.redis.aclose)
    stack.push_async_callback(cleanup, "transport shutdown", peer.transport.close_owner)
    # Startup keeps its own bound; deadline_seconds bounds only the proof body.
    deadline = asyncio.timeout(startup_deadline_seconds)
    try:
        async with deadline:
            lifespan = peer.worker_app.router.lifespan_context(peer.worker_app)
            await lifespan.__aenter__()
            stack.push_async_callback(
                cleanup, "worker lifespan shutdown", lifespan.__aexit__, None, None, None
            )
            stack.push_async_callback(cleanup, "generation shutdown", peer.stop_generation_tasks)
            for mode in scenario.loaded_modes:
                await peer.deps.cache.load(mode)
            if db_factory is not None:
                stack.push_async_callback(cleanup, "server shutdown", peer.stop_server)
                await peer.start_server(db_factory)
            peer.phase = "proof body"
            deadline.reschedule(asyncio.get_running_loop().time() + deadline_seconds)
            yield peer
            await stack.aclose()
    except TimeoutError as exc:
        if deadline.expired():
            raise TimeoutError(
                f"Worker peer timed out during {stalled_phase or peer.phase}"
            ) from exc
        raise
    finally:
        # Each remaining exit has its own bound after the proof deadline expires.
        await stack.aclose()


@pytest.fixture
def generation_worker_peer(tmp_path: Path):
    """S5-A/B/D, L3/L6/L9/L10: Own every resource of a shared worker scenario."""
    return partial(open_generation_worker_peer, tmp_path)
