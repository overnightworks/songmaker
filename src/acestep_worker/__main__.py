from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn
from redis.asyncio import Redis

from acestep_engine.constants import MODEL_CONFIG_PATHS
from acestep_worker.heartbeat import HeartbeatLoop
from acestep_worker.model_cache import ModelCache
from acestep_worker.registry_client import RegistryClient, WorkerRegistration
from acestep_worker.subprocess_runner import make_acestep_runner
from acestep_worker.task_store import TaskStore
from acestep_worker.wrapper import (
    WorkerDeps,
    build_state_payload,
    create_app,
    default_generate_runner,
)

DEFAULT_VRAM_BUDGET_GB = 22.0
DEFAULT_CHECKPOINT_DIR = Path("/app/_models/acestep")
DEFAULT_AUDIO_DIR = Path("/app/data/audio/worker_output")
DEFAULT_LOG_DIR = Path("/app/_models/acestep")
DEFAULT_ACESTEP_INNER_PORT = 8101

DEFAULT_MODEL_SIZES_GB: dict[str, float] = {
    "turbo": 6.0,
    "sft": 6.0,
    "xl-turbo": 12.0,
    "xl-sft": 12.0,
    "xl-base": 12.0,
}


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable not set: {name}")
    return value


def _optional_int_env(name: str) -> int | None:
    value = os.environ.get(name)
    return int(value) if value is not None and value != "" else None


def build_deps() -> WorkerDeps:
    worker_id = _require_env("WORKER_ID")
    worker_host = os.environ.get("WORKER_HOST", worker_id)
    worker_port = int(os.environ.get("WORKER_PORT", "8001"))
    vram_budget_gb = float(os.environ.get("VRAM_BUDGET_GB", str(DEFAULT_VRAM_BUDGET_GB)))
    checkpoint_dir = Path(os.environ.get("ACESTEP_CHECKPOINT_DIR", str(DEFAULT_CHECKPOINT_DIR)))
    audio_dir = Path(os.environ.get("AUDIO_OUTPUT_DIR", str(DEFAULT_AUDIO_DIR)))
    log_dir = Path(os.environ.get("ACESTEP_LOG_DIR", str(DEFAULT_LOG_DIR)))
    acestep_inner_port = int(
        os.environ.get("ACESTEP_INNER_PORT", str(DEFAULT_ACESTEP_INNER_PORT))
    )
    redis_url = _require_env("REDIS_URL")
    control_plane_url = os.environ.get("CONTROL_PLANE_URL")
    internal_token = os.environ.get("SONGMAKER_INTERNAL_TOKEN", "")

    redis_client: Redis = Redis.from_url(redis_url, decode_responses=False)

    loader, unloader = make_acestep_runner(
        checkpoint_dir=checkpoint_dir,
        base_port=acestep_inner_port,
        vram_budget_gb=vram_budget_gb,
        log_dir=log_dir,
    )
    cache = ModelCache(
        vram_budget_gb=vram_budget_gb,
        model_sizes={mode: DEFAULT_MODEL_SIZES_GB.get(mode, 6.0) for mode in MODEL_CONFIG_PATHS},
        loader=loader,
        unloader=unloader,
    )
    task_store = TaskStore()

    deps = WorkerDeps(
        worker_id=worker_id,
        cache=cache,
        task_store=task_store,
        heartbeat=None,  # type: ignore[arg-type]
        redis=redis_client,
        registry_client=None,
        registration=None,
        checkpoint_dir=checkpoint_dir,
        audio_output_dir=audio_dir,
        generate_runner=default_generate_runner,
    )

    deps.heartbeat = HeartbeatLoop(
        redis=redis_client,
        worker_id=worker_id,
        state_provider=lambda: build_state_payload(deps),
    )

    if control_plane_url and internal_token:
        deps.registry_client = RegistryClient(
            control_plane_url=control_plane_url,
            internal_token=internal_token,
        )
        deps.registration = WorkerRegistration(
            worker_id=worker_id,
            host=worker_host,
            port=worker_port,
            gpu_id=_optional_int_env("GPU_ID"),
            vram_total_gb=vram_budget_gb,
        )

    return deps


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    deps = build_deps()
    app = create_app(deps)
    port = int(os.environ.get("WORKER_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)  # noqa: S104


if __name__ == "__main__":  # pragma: no cover
    main()
