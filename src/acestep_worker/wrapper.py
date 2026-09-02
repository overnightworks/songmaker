from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis

from acestep_engine.models import AceStepConfig
from acestep_worker.downloads import (
    list_available_modes,
    spawn_background,
    start_download,
)
from acestep_worker.gpu_util import GpuHealth, GpuHealthStatus
from acestep_worker.heartbeat import HeartbeatLoop, queue_depth_key
from acestep_worker.model_cache import (
    CapacityError,
    ModelCache,
    ModelNotLoadedError,
    UnknownModeError,
)
from acestep_worker.models import (
    DownloadModelRequest,
    EvictModelRequest,
    EvictModelResponse,
    GenerateRequest,
    HealthResponse,
    LoadedModelDetailItem,
    LoadedModelsResponse,
    LoadModelRequest,
    LoadModelResponse,
    PinModelRequest,
    PinModelResponse,
    RestartResponse,
    TaskCreatedResponse,
    TaskSnapshot,
    TrainLoraRequest,
    UnpinModelRequest,
    WorkerTaskEvent,
)
from acestep_worker.registry_client import RegistryClient, WorkerRegistration
from acestep_worker.subprocess_runner import SubprocessStartError
from acestep_worker.task_store import TaskStore

log = logging.getLogger(__name__)

GenerateRunner = Any
TrainLoraRunner = Any


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
    train_lora_runner: TrainLoraRunner | None = None
    registered: bool = False
    registration_task: asyncio.Task[None] | None = None
    # Injectable so tests can simulate an NVML failure without a real GPU.
    # Defaults to "always healthy" so tests exercising unrelated endpoints
    # need not know about GPU health; __main__.py wires the real
    # gpu_util.check_gpu_health in production.
    gpu_health_checker: Callable[[], GpuHealth] = lambda: GpuHealth(GpuHealthStatus.OK)


def _format_sse(event: WorkerTaskEvent) -> bytes:
    payload = json.dumps(event.data, default=str)
    return f"event: {event.type}\ndata: {payload}\n\n".encode()


async def read_queue_depth(redis: Redis, worker_id: str) -> int:
    raw = await redis.get(queue_depth_key(worker_id))
    return int(raw) if raw is not None else 0


async def build_state_payload(deps: WorkerDeps) -> dict[str, Any]:
    snapshot = deps.cache.snapshot()
    gpu_health = deps.gpu_health_checker()
    return {
        "loaded": [
            {"mode": info.mode, "size_gb": info.size_gb}
            for info in snapshot.loaded
        ],
        "target_loading": snapshot.target_loading,
        "loading_started_at": (
            snapshot.loading_started_at.isoformat()
            if snapshot.loading_started_at is not None
            else None
        ),
        "loading_last_log_line": snapshot.loading_last_log_line,
        "vram_used_gb": snapshot.vram_used_gb,
        "vram_total_gb": snapshot.vram_total_gb,
        "vram_measured": snapshot.vram_measured,
        "available_modes": list_available_modes(deps.checkpoint_dir),
        "queue_depth": await read_queue_depth(deps.redis, deps.worker_id),
        "pinned": list(snapshot.pinned),
        "gpu_healthy": not gpu_health.is_broken,
        "gpu_health_detail": gpu_health.detail,
    }


def build_router(deps: WorkerDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        if not deps.registered:
            raise HTTPException(
                status_code=503,
                detail="awaiting control plane registration",
            )
        gpu_health = deps.gpu_health_checker()
        if gpu_health.is_broken:
            raise HTTPException(
                status_code=503,
                detail=f"GPU unavailable: {gpu_health.detail}",
            )
        return HealthResponse(status="ok")

    @router.get("/loaded_models", response_model=LoadedModelsResponse)
    async def loaded_models() -> LoadedModelsResponse:
        snapshot = deps.cache.snapshot()
        return LoadedModelsResponse(
            loaded=[
                LoadedModelDetailItem(mode=info.mode, size_gb=info.size_gb)
                for info in snapshot.loaded
            ],
            target_loading=snapshot.target_loading,
            loading_started_at=(
                snapshot.loading_started_at.isoformat()
                if snapshot.loading_started_at is not None
                else None
            ),
            loading_last_log_line=snapshot.loading_last_log_line,
            queue_depth=await read_queue_depth(deps.redis, deps.worker_id),
            vram_used_gb=snapshot.vram_used_gb,
            vram_total_gb=snapshot.vram_total_gb,
            vram_measured=snapshot.vram_measured,
            available_modes=list_available_modes(deps.checkpoint_dir),
            pinned=list(snapshot.pinned),
        )

    @router.post("/load_model", response_model=LoadModelResponse)
    async def load_model(req: LoadModelRequest) -> LoadModelResponse:
        try:
            result = await deps.cache.load(req.mode)
        except UnknownModeError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown mode: {exc}") from exc
        except CapacityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SubprocessStartError as exc:
            log.exception("ACE-Step subprocess failed to start for %s", req.mode)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return LoadModelResponse(
            loaded=result.loaded,
            evicted=result.evicted,
            target_loading=deps.cache.target_loading,
        )

    @router.post("/evict_model", response_model=EvictModelResponse)
    async def evict_model(req: EvictModelRequest) -> EvictModelResponse:
        try:
            evicted = await deps.cache.evict(req.mode)
        except CapacityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return EvictModelResponse(
            loaded=deps.cache.loaded_modes(),
            evicted=evicted,
        )

    @router.post("/pin_model", response_model=PinModelResponse)
    async def pin_model(req: PinModelRequest) -> PinModelResponse:
        try:
            await deps.cache.pin(req.mode)
        except ModelNotLoadedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        snapshot = deps.cache.snapshot()
        return PinModelResponse(mode=req.mode, pinned=list(snapshot.pinned))

    @router.post("/unpin_model", response_model=PinModelResponse)
    async def unpin_model(req: UnpinModelRequest) -> PinModelResponse:
        await deps.cache.unpin(req.mode)
        snapshot = deps.cache.snapshot()
        return PinModelResponse(mode=req.mode, pinned=list(snapshot.pinned))

    @router.post("/restart", response_model=RestartResponse)
    async def restart() -> RestartResponse:
        log.info("Restart requested via /restart endpoint")
        pid = os.getpid()
        loop = asyncio.get_running_loop()
        loop.call_later(0.1, lambda: os.kill(pid, signal.SIGTERM))
        return RestartResponse(status="restarting", pid=pid)

    @router.post("/generate", response_model=TaskCreatedResponse)
    async def generate(req: GenerateRequest) -> TaskCreatedResponse:
        loaded = await deps.cache.acquire_for_use(req.mode)
        if loaded is None:
            raise HTTPException(
                status_code=409,
                detail=f"Mode {req.mode} not loaded; call /load_model first",
            )
        try:
            task_id = await deps.task_store.create("generate")
        except Exception:
            await deps.cache.release(req.mode)
            raise

        async def _runner_with_release() -> None:
            try:
                await deps.generate_runner(
                    deps.task_store,
                    task_id,
                    mode=req.mode,
                    config=req.config,
                    port=loaded.port,
                    audio_output_dir=deps.audio_output_dir,
                )
            finally:
                await deps.cache.release(req.mode)

        spawn_background(_runner_with_release())
        return TaskCreatedResponse(task_id=task_id)

    @router.post("/tasks/train_lora", response_model=TaskCreatedResponse)
    async def train_lora(req: TrainLoraRequest) -> TaskCreatedResponse:
        if deps.train_lora_runner is None:
            raise HTTPException(
                status_code=501,
                detail="Worker not configured with a train_lora runner",
            )
        loaded = await deps.cache.acquire_for_use(req.mode)
        if loaded is None:
            raise HTTPException(
                status_code=409,
                detail=f"Mode {req.mode} not loaded; call /load_model first",
            )
        try:
            task_id = await deps.task_store.create("train_lora")
        except Exception:
            await deps.cache.release(req.mode)
            raise

        async def _runner_with_release() -> None:
            try:
                await deps.train_lora_runner(
                    deps.task_store,
                    task_id,
                    request=req,
                    port=loaded.port,
                )
            finally:
                await deps.cache.release(req.mode)

        spawn_background(_runner_with_release())
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
    control_plane = (
        deps.registry_client.control_plane_url
        if deps.registry_client is not None
        else "(disabled)"
    )
    log.info(
        "acestep-worker %s starting; awaiting control plane at %s",
        deps.worker_id, control_plane,
    )

    async def _register_and_flag() -> None:
        if deps.registry_client is not None and deps.registration is not None:
            await deps.registry_client.register(deps.registration)
        deps.registered = True

    deps.registration_task = asyncio.create_task(_register_and_flag())
    await deps.heartbeat.clear_orphaned_queue()
    deps.heartbeat.start()
    try:
        yield
    finally:
        if deps.registration_task is not None and not deps.registration_task.done():
            deps.registration_task.cancel()
            try:
                await deps.registration_task
            except (asyncio.CancelledError, Exception):
                pass
        await deps.heartbeat.shutdown()
        await deps.cache.evict_all()


def create_app(deps: WorkerDeps) -> FastAPI:
    app = FastAPI(title=f"acestep-worker:{deps.worker_id}", lifespan=lifespan)
    app.state.deps = deps
    app.include_router(build_router(deps))
    return app


async def default_train_lora_runner(
    task_store: TaskStore,
    task_id: str,
    *,
    request: TrainLoraRequest,
    port: int,
) -> None:
    from acestep_engine.models import LoraTrainingConfig
    from acestep_engine.training_client import (
        AceStepTrainingClient,
        TrainingRequestError,
        TrainingResponseError,
    )
    from acestep_worker.models import TrainLoraTaskResult

    await task_store.mark_running(task_id)
    client = AceStepTrainingClient(host="http://127.0.0.1", port=port)
    tensor_dir = str(Path(request.output_dir) / "tensors")
    loop = asyncio.get_running_loop()

    try:
        scan_result = await asyncio.to_thread(client.scan_dataset, request.dataset_dir)
        await task_store.update_progress(task_id, 0.02)
        if scan_result.num_samples == 0:
            raise RuntimeError(f"Dataset scan found 0 samples in {request.dataset_dir}")

        preprocess_handle = await asyncio.to_thread(
            client.start_preprocess, tensor_dir,
        )
        await task_store.update_progress(task_id, 0.05)

        while True:
            await asyncio.sleep(request.poll_interval_seconds)
            status = await asyncio.to_thread(
                client.poll_preprocess, preprocess_handle.task_id,
            )
            if status.total > 0:
                fraction = 0.05 + 0.15 * min(status.current / status.total, 1.0)
                await task_store.update_progress(task_id, fraction)
            if status.status == "completed":
                break
            if status.status == "failed":
                raise RuntimeError(f"Preprocess failed: {status.error or status.progress}")

        lokr_config = LoraTrainingConfig(
            tensor_dir=tensor_dir,
            output_dir=request.output_dir,
            lokr_linear_dim=request.lokr_linear_dim,
            lokr_linear_alpha=request.lokr_linear_alpha,
            lokr_factor=request.lokr_factor,
            lokr_decompose_both=request.lokr_decompose_both,
            lokr_use_tucker=request.lokr_use_tucker,
            lokr_use_scalar=request.lokr_use_scalar,
            lokr_weight_decompose=request.lokr_weight_decompose,
            learning_rate=request.learning_rate,
            train_epochs=request.train_epochs,
            train_batch_size=request.train_batch_size,
            gradient_accumulation=request.gradient_accumulation,
            save_every_n_epochs=request.save_every_n_epochs,
            training_shift=request.training_shift,
            training_seed=request.training_seed,
            gradient_checkpointing=request.gradient_checkpointing,
        )
        await asyncio.to_thread(client.start_lokr, lokr_config)
        await task_store.update_progress(task_id, 0.20)

        total_epochs = max(request.train_epochs, 1)
        final_loss: float | None = None
        while True:
            await asyncio.sleep(request.poll_interval_seconds)
            training_status = await asyncio.to_thread(client.poll_training)
            if training_status.current_loss is not None:
                final_loss = training_status.current_loss
            epoch_progress = min(training_status.current_epoch / total_epochs, 1.0)
            fraction = 0.20 + 0.70 * epoch_progress
            await task_store.update_progress(task_id, fraction)
            if training_status.error:
                raise RuntimeError(f"Training failed: {training_status.error}")
            if not training_status.is_training:
                break

        adapter_dir = str(Path(request.output_dir) / "final")
        export_result = await asyncio.to_thread(
            client.export_training, request.output_dir, adapter_dir,
        )
        await task_store.update_progress(task_id, 0.99)

        payload = TrainLoraTaskResult(
            mode=request.mode,
            adapter_dir=export_result.export_path,
            num_samples=scan_result.num_samples,
            final_loss=final_loss,
        )
        await task_store.complete(task_id, payload)
        del loop
    except asyncio.CancelledError:
        try:
            await asyncio.to_thread(client.stop_training)
        except (TrainingRequestError, TrainingResponseError, Exception):
            log.warning("Failed to stop training during cancel", exc_info=True)
        await task_store.fail(task_id, "cancelled")
        raise
    except Exception as exc:
        log.exception("Training failed for task %s", task_id)
        try:
            await asyncio.to_thread(client.stop_training)
        except Exception:
            log.debug("Best-effort stop_training failed", exc_info=True)
        await task_store.fail(task_id, f"{type(exc).__name__}: {exc}")


async def default_generate_runner(
    task_store: TaskStore,
    task_id: str,
    *,
    mode: str,
    config: AceStepConfig,
    port: int,
    audio_output_dir: Path,
) -> None:
    from acestep_engine.client import AceStepClient
    from acestep_engine.errors import AceStepError
    from acestep_worker.models import GenerationTaskResult
    from acestep_worker.progress import parse_step_fraction

    await task_store.mark_running(task_id)
    try:
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
            client.generate, config, on_progress=_on_progress,
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
            delivered_batch_size=result.delivered_batch_size,
        )
        await task_store.complete(task_id, payload)
    except Exception as exc:
        log.exception("Generation failed for task %s", task_id)
        cause = str(exc) if isinstance(exc, AceStepError) else f"{type(exc).__name__}: {exc}"
        await task_store.fail(task_id, cause)
