from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import shutil
import signal
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis

from acestep_engine.models import AceStepConfig
from acestep_worker.downloads import (
    list_available_modes,
    spawn_background,
    start_download,
)
from acestep_worker.gpu_util import GpuHealth, GpuHealthStatus
from acestep_worker.heartbeat import (
    DEFAULT_INTERVAL_SECONDS,
    DEFAULT_TTL_SECONDS,
    HeartbeatLoop,
    gpu_hold_key,
    gpu_hold_matches,
    queue_depth_key,
    release_gpu_hold,
    renew_gpu_hold,
    reserve_gpu_hold,
)
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
    GpuHoldHandoverResponse,
    GpuHoldResponse,
    GpuHoldTokenRequest,
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
from acestep_worker.settings import (
    DEFAULT_SHARED_AUDIO_ROOT,
    DEFAULT_TRAINING_WORKSPACE_DIRNAME,
)
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
    internal_token: str
    shared_audio_root: Path = Path(DEFAULT_SHARED_AUDIO_ROOT)
    training_workspace_dirname: str = DEFAULT_TRAINING_WORKSPACE_DIRNAME
    train_lora_runner: TrainLoraRunner | None = None
    registered: bool = False
    registration_task: asyncio.Task[None] | None = None
    gpu_hold_handover_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    gpu_hold_admission_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    gpu_hold_generation_tasks: set[str] = field(default_factory=set)
    gpu_hold_handover_tokens: set[str] = field(default_factory=set)
    gpu_hold_handover_tasks: dict[str, str] = field(default_factory=dict)
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


async def _renew_gpu_hold_until_done(
    redis: Redis,
    worker_id: str,
    token: str,
) -> None:
    while True:
        await asyncio.sleep(DEFAULT_INTERVAL_SECONDS)
        if not await renew_gpu_hold(redis, worker_id, token, DEFAULT_TTL_SECONDS):
            raise RuntimeError("GPU hold token was lost during LoRA training")


async def _start_gpu_hold_renewal(
    redis: Redis,
    worker_id: str,
    token: str,
) -> asyncio.Task[None]:
    if not await renew_gpu_hold(redis, worker_id, token, DEFAULT_TTL_SECONDS):
        raise RuntimeError("GPU hold token was lost before LoRA training started")
    return asyncio.create_task(_renew_gpu_hold_until_done(redis, worker_id, token))


async def _create_gpu_hold_handover_task(
    deps: WorkerDeps,
    token: str,
    *,
    train_epochs: int,
) -> str | None:
    async with deps.gpu_hold_handover_lock:
        if token in deps.gpu_hold_handover_tokens:
            return None
        if not await gpu_hold_matches(deps.redis, deps.worker_id, token):
            return None
        task_id = await deps.task_store.create("train_lora", train_epochs=train_epochs)
        deps.gpu_hold_handover_tokens.add(token)
        deps.gpu_hold_handover_tasks[token] = task_id
        return task_id


async def _release_gpu_hold_handover(deps: WorkerDeps, token: str) -> None:
    async with deps.gpu_hold_handover_lock:
        deps.gpu_hold_handover_tokens.discard(token)
        deps.gpu_hold_handover_tasks.pop(token, None)


async def _cancel_gpu_hold_renewal(renew_task: asyncio.Task[None]) -> None:
    if not renew_task.done():
        renew_task.cancel()
    try:
        await renew_task
    except asyncio.CancelledError:  # NOSONAR The owner cancels its renewal child.
        pass
    except Exception:
        log.exception("GPU hold renewal failed while its owner cleaned up")


async def build_state_payload(deps: WorkerDeps) -> dict[str, Any]:
    snapshot = deps.cache.snapshot()
    gpu_health = deps.gpu_health_checker()
    hold_seconds = await deps.redis.ttl(gpu_hold_key(deps.worker_id))
    return {
        "loaded": [{"mode": info.mode, "size_gb": info.size_gb} for info in snapshot.loaded],
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
        "training_hold_seconds": hold_seconds if hold_seconds > 0 else None,
        "pinned": list(snapshot.pinned),
        "gpu_healthy": not gpu_health.is_broken,
        "gpu_health_detail": gpu_health.detail,
    }


def build_router(deps: WorkerDeps) -> APIRouter:
    router = APIRouter()

    def verify_internal_token(
        x_internal_token: str = Header(..., alias="X-Internal-Token"),
    ) -> None:
        if not hmac.compare_digest(x_internal_token, deps.internal_token):
            raise HTTPException(status_code=401, detail="Invalid internal token")

    @router.get(
        "/health",
        response_model=HealthResponse,
        responses={503: {"description": "Worker is not ready or its GPU is unavailable"}},
    )
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

    @router.post(
        "/load_model",
        response_model=LoadModelResponse,
        responses={
            400: {"description": "Requested model mode is unknown"},
            409: {"description": "Insufficient capacity to load the model"},
            502: {"description": "Model subprocess could not be started"},
        },
    )
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

    @router.post(
        "/evict_model",
        response_model=EvictModelResponse,
        responses={409: {"description": "Model cannot be evicted"}},
    )
    async def evict_model(req: EvictModelRequest) -> EvictModelResponse:
        try:
            evicted = await deps.cache.evict(req.mode)
        except CapacityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return EvictModelResponse(
            loaded=deps.cache.loaded_modes(),
            evicted=evicted,
        )

    @router.post(
        "/pin_model",
        response_model=PinModelResponse,
        responses={409: {"description": "Model must be loaded before it can be pinned"}},
    )
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

    @router.post(
        "/generate",
        response_model=TaskCreatedResponse,
        dependencies=[Depends(verify_internal_token)],
        responses={409: {"description": "GPU is held or the requested model is not loaded"}},
    )
    async def generate(req: GenerateRequest) -> TaskCreatedResponse:
        async with deps.gpu_hold_admission_lock:
            if await deps.redis.exists(gpu_hold_key(deps.worker_id)):
                raise HTTPException(status_code=409, detail="GPU is held for LoRA training")
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
            deps.gpu_hold_generation_tasks.add(task_id)

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
                try:
                    await deps.cache.release(req.mode)
                finally:
                    async with deps.gpu_hold_admission_lock:
                        deps.gpu_hold_generation_tasks.discard(task_id)

        runner_with_release = _runner_with_release()
        try:
            spawn_background(runner_with_release)
        except Exception:
            runner_with_release.close()
            try:
                await deps.cache.release(req.mode)
            finally:
                async with deps.gpu_hold_admission_lock:
                    deps.gpu_hold_generation_tasks.discard(task_id)
            raise
        return TaskCreatedResponse(task_id=task_id)

    @router.post(
        "/gpu_hold/reserve",
        response_model=GpuHoldResponse,
        dependencies=[Depends(verify_internal_token)],
        responses={409: {"description": "GPU is busy or already held"}},
    )
    async def reserve_hold() -> GpuHoldResponse:
        token = str(uuid4())
        async with deps.gpu_hold_admission_lock:
            if deps.gpu_hold_generation_tasks:
                raise HTTPException(status_code=409, detail="GPU is busy or held")
            if not await reserve_gpu_hold(
                deps.redis,
                deps.worker_id,
                token,
                DEFAULT_TTL_SECONDS,
            ):
                raise HTTPException(status_code=409, detail="GPU is busy or held")
        return GpuHoldResponse(token=token)

    @router.post(
        "/gpu_hold/renew",
        status_code=204,
        dependencies=[Depends(verify_internal_token)],
        responses={409: {"description": "GPU hold token is invalid"}},
    )
    async def renew_hold(req: GpuHoldTokenRequest) -> None:
        if not await renew_gpu_hold(
            deps.redis,
            deps.worker_id,
            req.token,
            DEFAULT_TTL_SECONDS,
        ):
            raise HTTPException(status_code=409, detail="GPU hold token is invalid")

    @router.post(
        "/gpu_hold/release",
        status_code=204,
        dependencies=[Depends(verify_internal_token)],
        responses={409: {"description": "GPU hold token is invalid or owned by training"}},
    )
    async def release_hold(req: GpuHoldTokenRequest) -> None:
        async with deps.gpu_hold_handover_lock:
            if req.token in deps.gpu_hold_handover_tokens:
                raise HTTPException(
                    status_code=409,
                    detail="GPU hold is owned by a training task",
                )
            if not await release_gpu_hold(deps.redis, deps.worker_id, req.token):
                raise HTTPException(status_code=409, detail="GPU hold token is invalid")

    @router.post(
        "/gpu_hold/handover",
        response_model=GpuHoldHandoverResponse,
        dependencies=[Depends(verify_internal_token)],
    )
    async def hold_handover(req: GpuHoldTokenRequest) -> GpuHoldHandoverResponse:
        async with deps.gpu_hold_handover_lock:
            task_id = deps.gpu_hold_handover_tasks.get(req.token)
            return GpuHoldHandoverResponse(
                claimed=task_id is not None,
                task_id=task_id,
            )

    @router.post(
        "/tasks/train_lora",
        response_model=TaskCreatedResponse,
        dependencies=[Depends(verify_internal_token)],
        responses={
            409: {"description": "GPU hold or requested model is unavailable"},
            422: {"description": "Training request is invalid"},
            501: {"description": "Worker does not support LoRA training"},
        },
    )
    async def train_lora(req: TrainLoraRequest) -> TaskCreatedResponse:
        try:
            validated_request = _validate_train_lora_request(
                req,
                deps.shared_audio_root,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if deps.train_lora_runner is None:
            raise HTTPException(
                status_code=501,
                detail="Worker not configured with a train_lora runner",
            )
        loaded = None
        renew_task = None
        task_id = None
        try:
            loaded = await deps.cache.acquire_for_use(req.mode)
            if loaded is None:
                raise HTTPException(
                    status_code=409,
                    detail=f"Mode {req.mode} not loaded; call /load_model first",
                )
            try:
                renew_task = await _start_gpu_hold_renewal(
                    deps.redis,
                    deps.worker_id,
                    req.hold_token,
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            task_id = await _create_gpu_hold_handover_task(
                deps,
                req.hold_token,
                train_epochs=req.train_epochs,
            )
            if task_id is None:
                raise HTTPException(
                    status_code=409,
                    detail="GPU hold token is invalid or already handed over",
                )
        except BaseException:
            try:
                if renew_task is not None:
                    await _cancel_gpu_hold_renewal(renew_task)
            finally:
                try:
                    if loaded is not None:
                        await deps.cache.release(req.mode)
                finally:
                    await _release_gpu_hold_handover(deps, req.hold_token)
            raise

        async def _runner_with_release() -> None:
            training_task = asyncio.create_task(
                deps.train_lora_runner(
                    deps.task_store,
                    task_id,
                    request=validated_request,
                    port=loaded.port,
                    checkpoint_dir=deps.checkpoint_dir,
                    training_workspace_dirname=deps.training_workspace_dirname,
                ),
            )
            try:
                done, _ = await asyncio.wait(
                    {training_task, renew_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if renew_task in done:
                    training_task.cancel()
                    try:
                        await training_task
                    except asyncio.CancelledError:  # NOSONAR The supervisor cancels this child.
                        pass
                    await renew_task
                await training_task
            finally:
                try:
                    if not training_task.done():
                        training_task.cancel()
                        try:
                            await training_task
                        except asyncio.CancelledError:  # NOSONAR The parent cancels this child.
                            pass
                finally:
                    await _cancel_gpu_hold_renewal(renew_task)
                    try:
                        await release_gpu_hold(deps.redis, deps.worker_id, req.hold_token)
                    finally:
                        try:
                            await deps.cache.release(req.mode)
                        finally:
                            await _release_gpu_hold_handover(deps, req.hold_token)

        runner_with_release = _runner_with_release()
        try:
            spawn_background(runner_with_release)
        except Exception:
            runner_with_release.close()
            try:
                await _cancel_gpu_hold_renewal(renew_task)
            finally:
                try:
                    await release_gpu_hold(deps.redis, deps.worker_id, req.hold_token)
                finally:
                    try:
                        await deps.cache.release(req.mode)
                    finally:
                        await _release_gpu_hold_handover(deps, req.hold_token)
            raise
        return TaskCreatedResponse(task_id=task_id)

    @router.post("/download_model", response_model=TaskCreatedResponse)
    async def download_model(req: DownloadModelRequest) -> TaskCreatedResponse:
        task_id = await start_download(
            deps.task_store,
            mode=req.mode,
            checkpoint_dir=deps.checkpoint_dir,
        )
        return TaskCreatedResponse(task_id=task_id)

    @router.get(
        "/tasks/{task_id}",
        response_model=TaskSnapshot,
        responses={404: {"description": "Task does not exist"}},
    )
    async def get_task(task_id: str) -> TaskSnapshot:
        snapshot = await deps.task_store.get(task_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"Unknown task: {task_id}")
        return snapshot

    @router.get(
        "/tasks/{task_id}/stream",
        responses={404: {"description": "Task does not exist"}},
    )
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
        deps.registry_client.control_plane_url if deps.registry_client is not None else "(disabled)"
    )
    log.info(
        "acestep-worker %s starting; awaiting control plane at %s",
        deps.worker_id,
        control_plane,
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
    checkpoint_dir: Path,
    training_workspace_dirname: str,
) -> None:
    from acestep_engine.models import LoraTrainingConfig
    from acestep_engine.training_client import AceStepTrainingClient
    from acestep_worker.models import TrainLoraTaskResult

    await task_store.mark_running(task_id)
    client = AceStepTrainingClient(host="http://127.0.0.1", port=port)
    workspace = checkpoint_dir / training_workspace_dirname / task_id
    dataset_dir = workspace / "dataset"
    output_dir = workspace / "output"
    export_dir = workspace / "export"

    try:
        source_dataset_dir = Path(request.dataset_dir)
        requested_output_dir = Path(request.output_dir)
        if workspace.is_relative_to(source_dataset_dir):
            raise ValueError(
                f"LoRA workspace must not be nested in dataset: {source_dataset_dir}",
            )
        await asyncio.to_thread(shutil.rmtree, workspace, ignore_errors=True)
        await asyncio.to_thread(workspace.mkdir, parents=True, exist_ok=True)
        await _copytree_before_cleanup(source_dataset_dir, dataset_dir)
        await asyncio.to_thread(client.initialize_model, request.mode)
        scan_result = await asyncio.to_thread(client.scan_dataset, str(dataset_dir))
        await task_store.update_progress(task_id, 0.02)
        if scan_result.num_samples == 0:
            raise RuntimeError(f"Dataset scan found 0 samples in {dataset_dir}")

        preprocess_handle = await asyncio.to_thread(
            client.start_preprocess,
            str(output_dir / "tensors"),
        )
        await task_store.update_progress(task_id, 0.05)

        while True:
            await asyncio.sleep(request.poll_interval_seconds)
            status = await asyncio.to_thread(
                client.poll_preprocess,
                preprocess_handle.task_id,
            )
            if status.total > 0:
                fraction = 0.05 + 0.15 * min(status.current / status.total, 1.0)
                await task_store.update_progress(task_id, fraction)
            if status.status == "completed":
                break
            if status.status == "failed":
                raise RuntimeError(f"Preprocess failed: {status.error or status.progress}")

        lokr_config = LoraTrainingConfig(
            tensor_dir=str(output_dir / "tensors"),
            output_dir=str(output_dir),
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
        await task_store.mark_training_started(task_id)
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
            await task_store.update_progress(
                task_id,
                fraction,
                current_epoch=training_status.current_epoch,
            )
            if training_status.error:
                raise RuntimeError(f"Training failed: {training_status.error}")
            if not training_status.is_training:
                break

        export_result = await asyncio.to_thread(
            client.export_training,
            str(output_dir),
            str(export_dir),
        )
        if Path(export_result.source).resolve() != (output_dir / "final").resolve():
            raise RuntimeError(
                f"ACE-Step exported an unexpected source: {export_result.source}",
            )
        if Path(export_result.export_path).resolve() != export_dir.resolve():
            raise RuntimeError(
                f"ACE-Step exported to an unexpected path: {export_result.export_path}",
            )
        if not export_dir.is_dir():
            raise RuntimeError(f"ACE-Step export is missing: {export_dir}")
        await asyncio.to_thread(requested_output_dir.parent.mkdir, parents=True, exist_ok=True)
        await _copytree_before_cleanup(export_dir, requested_output_dir)
        await task_store.update_progress(task_id, 0.99)

        payload = TrainLoraTaskResult(
            mode=request.mode,
            adapter_dir=str(requested_output_dir),
            num_samples=scan_result.num_samples,
            final_loss=final_loss,
        )
        await task_store.complete(task_id, payload)
    except asyncio.CancelledError:
        try:
            await asyncio.to_thread(client.stop_training)
        except Exception:
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
    finally:
        try:
            await asyncio.to_thread(shutil.rmtree, workspace)
        except FileNotFoundError:
            pass
        except OSError:
            log.exception("Failed to remove LoRA training workspace %s", workspace)


def _validate_train_lora_request(
    request: TrainLoraRequest,
    shared_audio_root: Path,
) -> TrainLoraRequest:
    dataset_dir = _shared_audio_path(request.dataset_dir, shared_audio_root, "dataset")
    output_dir = _shared_audio_path(request.output_dir, shared_audio_root, "output")
    return request.model_copy(
        update={
            "dataset_dir": str(dataset_dir),
            "output_dir": str(output_dir),
        }
    )


def _shared_audio_path(path: str, root: Path, kind: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink():
        raise ValueError(f"LoRA {kind} path must not be a symlink: {candidate}")
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError(f"LoRA {kind} path is outside shared audio root: {candidate}")
    if kind == "dataset" and not resolved.is_dir():
        raise ValueError(f"LoRA dataset path is not a directory: {candidate}")
    if kind == "output" and (resolved == resolved_root or resolved.exists()):
        raise ValueError(f"LoRA output path must be a new shared directory: {candidate}")
    return resolved


async def _copytree_before_cleanup(source: Path, destination: Path) -> None:
    copy_task = asyncio.create_task(
        asyncio.to_thread(shutil.copytree, source, destination, symlinks=False),
    )
    try:
        await asyncio.shield(copy_task)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(copy_task)
        except Exception:
            log.exception("LoRA copy failed while cancellation was pending")
        raise


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
                task_store.update_progress(task_id, fraction),
                loop,
            )

        result = await asyncio.to_thread(
            client.generate,
            config,
            on_progress=_on_progress,
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
