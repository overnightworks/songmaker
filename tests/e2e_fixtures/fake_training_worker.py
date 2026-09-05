"""Test-only ACE-Step worker for the Voices compose override."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import struct
import wave
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from redis.asyncio import Redis

from acestep_worker.heartbeat import HeartbeatLoop
from acestep_worker.model_cache import LoadedModel, ModelCache
from acestep_worker.models import GenerationTaskResult, TrainLoraRequest, TrainLoraTaskResult
from acestep_worker.registry_client import RegistryClient, WorkerRegistration
from acestep_worker.task_store import TaskStore
from acestep_worker.wrapper import WorkerDeps, build_state_payload, create_app

DEFAULT_BIND_HOST = "0.0.0.0"
DEFAULT_CONTROL_PLANE_URL = "http://songmaker-web:8080"
DEFAULT_PORT = 8001
DEFAULT_PROGRESS_PAUSE_SECONDS = 1.0
# Keep the one fake GPU occupied while the browser adds two training jobs and
# retries a failed voice. This makes the configured queue-capacity evidence
# deterministic without seeding a queue state.
FAKE_GENERATION_OCCUPANCY_SECONDS = 15.0
FAKE_GENERATION_OCCUPANCY_PROMPT = "E2E voices occupancy prompt"
FAKE_FAILED_TRAINING_CAPTION = "e2e fake training failure"
FAKE_WORKER_ID = "voices-e2e-training-worker"
FAKE_WORKER_HOST = "songmaker-voices-e2e-worker"
FAKE_WORKER_VRAM_GB = 1.0
FAKE_MODEL_MODE = "sft"
FAKE_MODEL_SIZE_GB = 0.1


@dataclass(frozen=True)
class FakeTrainingWorkerSettings:
    redis_url: str
    internal_token: str
    audio_dir: Path
    control_plane_url: str = DEFAULT_CONTROL_PLANE_URL
    worker_id: str = FAKE_WORKER_ID
    worker_host: str = FAKE_WORKER_HOST
    port: int = DEFAULT_PORT
    generation_occupancy_prompt: str = FAKE_GENERATION_OCCUPANCY_PROMPT

    @classmethod
    def from_environment(cls) -> FakeTrainingWorkerSettings:
        return cls(
            redis_url=os.environ["REDIS_URL"],
            internal_token=os.environ["SONGMAKER_INTERNAL_TOKEN"],
            audio_dir=Path(os.environ["AUDIO_DIR"]),
            control_plane_url=os.environ.get("CONTROL_PLANE_URL", DEFAULT_CONTROL_PLANE_URL),
            worker_id=os.environ.get("WORKER_ID", FAKE_WORKER_ID),
            worker_host=os.environ.get("WORKER_HOST", FAKE_WORKER_HOST),
            port=int(os.environ.get("WORKER_PORT", DEFAULT_PORT)),
            generation_occupancy_prompt=os.environ.get(
                "FAKE_GENERATION_OCCUPANCY_PROMPT", FAKE_GENERATION_OCCUPANCY_PROMPT
            ),
        )


async def _fake_model_loader(mode: str) -> LoadedModel:
    return LoadedModel(mode=mode, handle=object(), port=DEFAULT_PORT)


async def _discard_model(_: LoadedModel) -> None:
    return None


def fake_generation_wav_bytes(prompt: str, seed: int, lora_path: str | None) -> bytes:
    """Build the deterministic one-second WAV used by the Voices browser proof."""
    payload = json.dumps(
        [prompt, seed, lora_path or ""], ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    samples = ((digest[index % len(digest)] - 128) * 256 for index in range(8_000))
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8_000)
        wav.writeframes(struct.pack("<8000h", *samples))
    return output.getvalue()


def _is_occupancy_generation(config: object, occupancy_prompt: str) -> bool:
    return getattr(config, "prompt", None) == occupancy_prompt


async def _queued_generate_runner(
    task_store: TaskStore,
    task_id: str,
    *,
    config: object,
    audio_output_dir: Path,
    occupancy_prompt: str = FAKE_GENERATION_OCCUPANCY_PROMPT,
    **_: object,
) -> None:
    """Occupy only the named S5 proof; every other request gets a fake WAV."""
    await task_store.mark_running(task_id)
    if _is_occupancy_generation(config, occupancy_prompt):
        await asyncio.sleep(FAKE_GENERATION_OCCUPANCY_SECONDS)
        await task_store.fail(task_id, "E2E fake generation released the training worker")
        return

    prompt = getattr(config, "prompt", "")
    seed = getattr(config, "seed", -1)
    lora_path = getattr(config, "lora_path", None)
    is_valid_config = (
        isinstance(prompt, str)
        and isinstance(seed, int)
        and isinstance(lora_path, str | None)
    )
    if not is_valid_config:
        raise TypeError("Fake generation requires prompt, seed, and lora_path on its config")
    audio_output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_output_dir / f"{task_id}.wav"
    audio_path.write_bytes(fake_generation_wav_bytes(prompt, seed, lora_path))
    await task_store.complete(
        task_id,
        GenerationTaskResult(mode=FAKE_MODEL_MODE, audio_path=str(audio_path), seed=seed),
    )


async def _fake_train_lora_runner(
    task_store: TaskStore,
    task_id: str,
    *,
    request: TrainLoraRequest,
    port: int,
    checkpoint_dir: Path,
    training_workspace_dirname: str,
) -> None:
    del port, checkpoint_dir, training_workspace_dirname
    output_dir = Path(request.output_dir)
    output_dir.mkdir(parents=True)
    (output_dir / "adapter_model.safetensors").write_bytes(b"voices-e2e-adapter")

    await task_store.mark_running(task_id)
    await task_store.mark_training_started(task_id)
    captions = Path(request.dataset_dir).glob("*.caption.txt")
    if any(FAKE_FAILED_TRAINING_CAPTION in caption.read_text() for caption in captions):
        await task_store.fail(task_id, "E2E fake training failure requested by its sample")
        return
    for current_epoch in (0, request.train_epochs // 2, request.train_epochs):
        await task_store.update_progress(
            task_id,
            current_epoch / request.train_epochs,
            current_epoch=current_epoch,
        )
        await asyncio.sleep(DEFAULT_PROGRESS_PAUSE_SECONDS)
    await task_store.complete(
        task_id,
        TrainLoraTaskResult(
            mode=request.mode,
            adapter_dir=str(output_dir),
            num_samples=len(list(Path(request.dataset_dir).glob("*.caption.txt"))),
        ),
    )


def build_fake_worker_deps(
    settings: FakeTrainingWorkerSettings,
    *,
    redis: Redis | None = None,
) -> WorkerDeps:
    redis_client = redis or Redis.from_url(settings.redis_url, decode_responses=False)
    registry_client = (
        RegistryClient(
            control_plane_url=settings.control_plane_url,
            internal_token=settings.internal_token,
        )
        if settings.control_plane_url
        else None
    )
    cache = ModelCache(
        vram_budget_gb=FAKE_WORKER_VRAM_GB,
        model_sizes={FAKE_MODEL_MODE: FAKE_MODEL_SIZE_GB},
        loader=_fake_model_loader,
        unloader=_discard_model,
    )
    deps = WorkerDeps(
        worker_id=settings.worker_id,
        cache=cache,
        task_store=TaskStore(),
        heartbeat=None,  # type: ignore[arg-type]
        redis=redis_client,
        registry_client=registry_client,
        registration=WorkerRegistration(
            worker_id=settings.worker_id,
            host=settings.worker_host,
            port=settings.port,
            gpu_id=None,
            vram_total_gb=FAKE_WORKER_VRAM_GB,
        ),
        checkpoint_dir=settings.audio_dir,
        audio_output_dir=settings.audio_dir,
        generate_runner=lambda task_store, task_id, **kwargs: _queued_generate_runner(
            task_store,
            task_id,
            occupancy_prompt=settings.generation_occupancy_prompt,
            **kwargs,
        ),
        internal_token=settings.internal_token,
        shared_audio_root=settings.audio_dir,
        train_lora_runner=_fake_train_lora_runner,
    )
    deps.heartbeat = HeartbeatLoop(
        redis=redis_client,
        worker_id=settings.worker_id,
        state_provider=lambda: build_state_payload(deps),
    )
    return deps


def create_fake_training_worker_app(
    settings: FakeTrainingWorkerSettings,
    *,
    redis: Redis | None = None,
):
    return create_app(build_fake_worker_deps(settings, redis=redis))


def main() -> None:
    settings = FakeTrainingWorkerSettings.from_environment()
    app = create_fake_training_worker_app(settings)
    uvicorn.run(app, host=DEFAULT_BIND_HOST, port=settings.port)


if __name__ == "__main__":  # pragma: no cover
    main()
