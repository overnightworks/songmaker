from __future__ import annotations

import logging
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
from songmaker_cli.settings import WorkerSettings, get_worker_settings

DEFAULT_MODEL_SIZES_GB: dict[str, float] = {
    "turbo": 6.0,
    "sft": 6.0,
    "xl-turbo": 12.0,
    "xl-sft": 12.0,
    "xl-base": 12.0,
}


def build_deps(settings: WorkerSettings | None = None) -> WorkerDeps:
    settings = settings or get_worker_settings()
    worker_id = settings.worker_id
    worker_host = settings.worker_host or worker_id
    checkpoint_dir = Path(settings.acestep_checkpoint_dir)
    audio_dir = Path(settings.audio_output_dir)
    log_dir = Path(settings.acestep_log_dir)

    redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=False)

    loader, unloader = make_acestep_runner(
        checkpoint_dir=checkpoint_dir,
        base_port=settings.acestep_inner_port,
        vram_budget_gb=settings.vram_budget_gb,
        log_dir=log_dir,
    )
    cache = ModelCache(
        vram_budget_gb=settings.vram_budget_gb,
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

    internal_token = settings.songmaker_internal_token.get_secret_value()
    if settings.control_plane_url and internal_token:
        deps.registry_client = RegistryClient(
            control_plane_url=settings.control_plane_url,
            internal_token=internal_token,
        )
        deps.registration = WorkerRegistration(
            worker_id=worker_id,
            host=worker_host,
            port=settings.worker_port,
            gpu_id=settings.gpu_id,
            vram_total_gb=settings.vram_budget_gb,
        )

    return deps


def main() -> None:
    settings = get_worker_settings()
    logging.basicConfig(level=settings.log_level)
    deps = build_deps(settings)
    app = create_app(deps)
    uvicorn.run(app, host="0.0.0.0", port=settings.worker_port)  # noqa: S104


if __name__ == "__main__":  # pragma: no cover
    main()
