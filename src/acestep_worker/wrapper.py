from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis

from acestep_worker.downloads import (
    list_available_modes,
    spawn_background,
    start_download,
)
from acestep_worker.heartbeat import HeartbeatLoop, queue_depth_key
from acestep_worker.model_cache import (
    CapacityError,
    ModelCache,
    UnknownModeError,
)
from acestep_worker.models import (
    DownloadModelRequest,
    EvictModelRequest,
    EvictModelResponse,
    GenerateRequest,
    HealthResponse,
    LoadedModelsResponse,
    LoadModelRequest,
    LoadModelResponse,
    TaskCreatedResponse,
    TaskSnapshot,
    WorkerTaskEvent,
)
from acestep_worker.registry_client import RegistryClient, WorkerRegistration
from acestep_worker.task_store import TaskStore

log = logging.getLogger(__name__)

GenerateRunner = Any


@dataclass
class WorkerDeps:
    worker_id: str
    cache: ModelCache
    task_store: TaskStore
    heartbeat: HeartbeatLoop
    redis: Redis
    registry_client: RegistryClient | None
    registration: WorkerRegistration | None
    checkpoint_dir: Path
    audio_output_dir: Path
    generate_runner: GenerateRunner


def _format_sse(event: WorkerTaskEvent) -> bytes:
    payload = json.dumps(event.data, default=str)
    return f"event: {event.type}\ndata: {payload}\n\n".encode()


async def read_queue_depth(redis: Redis, worker_id: str) -> int:
    raw = await redis.get(queue_depth_key(worker_id))
    return int(raw) if raw is not None else 0


async def build_state_payload(deps: WorkerDeps) -> dict[str, Any]:
    snapshot = deps.cache.snapshot()
    return {
        "loaded": list(snapshot.loaded),
        "target_loading": snapshot.target_loading,
        "vram_used_gb": snapshot.vram_used_gb,
        "vram_total_gb": snapshot.vram_total_gb,
        "available_modes": list_available_modes(deps.checkpoint_dir),
        "queue_depth": await read_queue_depth(deps.redis, deps.worker_id),
    }


def build_router(deps: WorkerDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @router.get("/loaded_models", response_model=LoadedModelsResponse)
    async def loaded_models() -> LoadedModelsResponse:
        snapshot = deps.cache.snapshot()
        return LoadedModelsResponse(
            loaded=list(snapshot.loaded),
            target_loading=snapshot.target_loading,
            queue_depth=await read_queue_depth(deps.redis, deps.worker_id),
            vram_used_gb=snapshot.vram_used_gb,
            vram_total_gb=snapshot.vram_total_gb,
            available_modes=list_available_modes(deps.checkpoint_dir),
        )

    @router.post("/load_model", response_model=LoadModelResponse)
    async def load_model(req: LoadModelRequest) -> LoadModelResponse:
        try:
            result = await deps.cache.load(req.mode)
        except UnknownModeError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown mode: {exc}") from exc
        except CapacityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return LoadModelResponse(
            loaded=result.loaded,
            evicted=result.evicted,
            target_loading=deps.cache.target_loading,
        )

    @router.post("/evict_model", response_model=EvictModelResponse)
    async def evict_model(req: EvictModelRequest) -> EvictModelResponse:
        evicted = await deps.cache.evict(req.mode)
        return EvictModelResponse(
            loaded=deps.cache.loaded_modes(),
            evicted=evicted,
        )

    @router.post("/generate", response_model=TaskCreatedResponse)
    async def generate(req: GenerateRequest) -> TaskCreatedResponse:
        loaded = deps.cache.get_loaded(req.mode)
        if loaded is None:
            raise HTTPException(
                status_code=409,
                detail=f"Mode {req.mode} not loaded; call /load_model first",
            )
        task_id = await deps.task_store.create("generate")
        spawn_background(
            deps.generate_runner(
                deps.task_store,
                task_id,
                mode=req.mode,
                config=req.config,
                port=loaded.port,
                audio_output_dir=deps.audio_output_dir,
            )
        )
        return TaskCreatedResponse(task_id=task_id)

    @router.post("/download_model", response_model=TaskCreatedResponse)
    async def download_model(req: DownloadModelRequest) -> TaskCreatedResponse:
        task_id = await start_download(
            deps.task_store,
            mode=req.mode,
            checkpoint_dir=deps.checkpoint_dir,
        )
        return TaskCreatedResponse(task_id=task_id)

    @router.get("/tasks/{task_id}", response_model=TaskSnapshot)
    async def get_task(task_id: str) -> TaskSnapshot:
        snapshot = await deps.task_store.get(task_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"Unknown task: {task_id}")
        return snapshot

    @router.get("/tasks/{task_id}/stream")
    async def stream_task(task_id: str) -> StreamingResponse:
        snapshot = await deps.task_store.get(task_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"Unknown task: {task_id}")

        async def event_source() -> AsyncIterator[bytes]:
            async for event in deps.task_store.subscribe(task_id):
                yield _format_sse(event)

        return StreamingResponse(event_source(), media_type="text/event-stream")

    return router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    deps: WorkerDeps = app.state.deps
    if deps.registry_client is not None and deps.registration is not None:
        await deps.registry_client.register(deps.registration)
    await deps.heartbeat.clear_orphaned_queue()
    deps.heartbeat.start()
    try:
        yield
    finally:
        await deps.heartbeat.shutdown()
        await deps.cache.evict_all()


def create_app(deps: WorkerDeps) -> FastAPI:
    app = FastAPI(title=f"acestep-worker:{deps.worker_id}", lifespan=lifespan)
    app.state.deps = deps
    app.include_router(build_router(deps))
    return app


async def default_generate_runner(
    task_store: TaskStore,
    task_id: str,
    *,
    mode: str,
    config: dict[str, Any],
    port: int,
    audio_output_dir: Path,
) -> None:
    from acestep_engine.client import AceStepClient
    from acestep_engine.models import AceStepConfig
    from acestep_worker.models import GenerationTaskResult
    from acestep_worker.progress import parse_step_fraction

    await task_store.mark_running(task_id)
    try:
        ace_config = AceStepConfig(**config)
        client = AceStepClient(host="http://127.0.0.1", port=port)

        loop = asyncio.get_running_loop()

        def _on_progress(text: str) -> None:
            fraction = parse_step_fraction(text)
            if fraction is None:
                return
            asyncio.run_coroutine_threadsafe(
                task_store.update_progress(task_id, fraction), loop,
            )

        result = await asyncio.to_thread(
            client.generate, ace_config, on_progress=_on_progress,
        )
        audio_output_dir.mkdir(parents=True, exist_ok=True)
        out_path = audio_output_dir / f"{task_id}-{uuid4().hex[:8]}.wav"
        out_path.write_bytes(result.wav_bytes)
        payload = GenerationTaskResult(
            mode=mode,
            audio_path=str(out_path),
            seed=result.seed,
            cot_caption=result.cot_caption,
            cot_lyrics=result.cot_lyrics,
        )
        await task_store.complete(task_id, payload.model_dump())
    except Exception as exc:
        log.exception("Generation failed for task %s", task_id)
        await task_store.fail(task_id, f"{type(exc).__name__}: {exc}")
