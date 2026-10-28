from __future__ import annotations

import json
import logging
import os
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from redis.asyncio import Redis
from uvicorn.main import STARTUP_FAILURE

from acestep_engine.constants import MODEL_CONFIG_PATHS
from acestep_worker.gpu_util import check_gpu_health, read_gpu_vram_stats
from acestep_worker.heartbeat import HeartbeatLoop
from acestep_worker.model_cache import ModelCache
from acestep_worker.registry_client import RegistryClient, WorkerRegistration
from acestep_worker.settings import WorkerSettings, get_worker_settings
from acestep_worker.subprocess_runner import make_acestep_runner
from acestep_worker.task_store import TaskStore
from acestep_worker.wrapper import (
    WorkerDeps,
    build_state_payload,
    create_app,
    default_generate_runner,
    default_train_lora_runner,
)

# Bounds the wait for open responses once the server was asked to stop.
GRACEFUL_SHUTDOWN_SECONDS = 10
# A running take's polling thread outlives its cancelled coroutine and holds the interpreter
# open for the poll timeout, so a requested exit is forced after this long.
FORCED_EXIT_SECONDS = GRACEFUL_SHUTDOWN_SECONDS + 20.0

DEFAULT_MODEL_SIZES_GB: dict[str, float] = {
    "turbo": 6.0,
    "sft": 6.0,
    "xl-turbo": 12.0,
    "xl-sft": 12.0,
    "xl-base": 12.0,
}
# The 4B LM is about 8 GB of bf16 weights, plus the 1.13 GB KV floor and about
# 1.4 GB of CUDA context (docs/acestep.md); the smaller 1.7B LM only evicts sooner.
LM_DECLARED_SIZE_GB = 10.0


def declared_model_sizes(settings: WorkerSettings) -> dict[str, float]:
    lm_size_gb = LM_DECLARED_SIZE_GB if settings.acestep_init_llm else 0.0
    return {
        mode: DEFAULT_MODEL_SIZES_GB.get(mode, 6.0) + lm_size_gb for mode in MODEL_CONFIG_PATHS
    }


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


class _AcestepWorkerLogHandler(logging.StreamHandler):
    pass


def configure_logging(log_level: str) -> None:
    handler = _AcestepWorkerLogHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for existing_handler in root.handlers[:]:
        if isinstance(existing_handler, _AcestepWorkerLogHandler):
            root.removeHandler(existing_handler)
            existing_handler.close()
    root.addHandler(handler)
    root.setLevel(log_level)


def build_deps(settings: WorkerSettings | None = None) -> WorkerDeps:
    settings = settings or get_worker_settings()
    worker_id = settings.worker_id
    worker_host = settings.worker_host or worker_id
    checkpoint_dir = Path(settings.acestep_checkpoint_dir)
    audio_dir = Path(settings.audio_output_dir)
    shared_audio_root = Path(settings.shared_audio_root)
    log_dir = Path(settings.acestep_log_dir)

    redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=False)

    cache_box: dict[str, ModelCache] = {}

    def on_log_line(line: str) -> None:
        cache = cache_box.get("cache")
        if cache is not None:
            cache.set_loading_log_line(line)

    log_sink: Callable[[str], None] = on_log_line

    loader, unloader = make_acestep_runner(
        checkpoint_dir=checkpoint_dir,
        base_port=settings.acestep_inner_port,
        vram_budget_gb=settings.vram_budget_gb,
        gpu_id=settings.gpu_id,
        log_dir=log_dir,
        on_log_line=log_sink,
    )
    cache = ModelCache(
        vram_budget_gb=settings.vram_budget_gb,
        model_sizes=declared_model_sizes(settings),
        loader=loader,
        unloader=unloader,
        vram_reader=lambda: read_gpu_vram_stats(settings.gpu_id or 0),
    )
    cache_box["cache"] = cache
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
        internal_token=settings.songmaker_internal_token.get_secret_value(),
        shared_audio_root=shared_audio_root,
        training_workspace_dirname=settings.acestep_training_workspace_dirname,
        generate_runner=default_generate_runner,
        train_lora_runner=default_train_lora_runner,
        gpu_health_checker=lambda: check_gpu_health(settings.gpu_id or 0),
    )

    deps.heartbeat = HeartbeatLoop(
        redis=redis_client,
        worker_id=worker_id,
        state_provider=lambda: build_state_payload(deps),
    )

    if settings.control_plane_url:
        deps.registry_client = RegistryClient(
            control_plane_url=settings.control_plane_url,
            internal_token=settings.songmaker_internal_token.get_secret_value(),
        )
        deps.registration = WorkerRegistration(
            worker_id=worker_id,
            host=worker_host,
            port=settings.worker_port,
            gpu_id=settings.gpu_id,
            vram_total_gb=settings.vram_budget_gb,
        )

    return deps


def serve(
    deps: WorkerDeps,
    host: str,
    port: int,
    *,
    force_exit: Callable[[int], object] = os._exit,
    forced_exit_seconds: float = FORCED_EXIT_SECONDS,
) -> int:
    """Run the server until it stops; returns the exit code the process owes.

    A requested exit that the shutdown does not finish within `forced_exit_seconds` ends the
    process through `force_exit`, so a running take cannot delay the restart.
    """
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(deps),
            host=host,
            port=port,
            log_config=None,
            timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
        )
    )
    exit_codes: list[int] = []
    watchdogs: list[threading.Timer] = []

    def request_shutdown(exit_code: int) -> None:
        # A signal would make uvicorn re-raise it after the shutdown and lose the exit code.
        exit_codes.append(exit_code)
        server.should_exit = True
        watchdog = threading.Timer(forced_exit_seconds, force_exit, args=(exit_code,))
        watchdog.daemon = True
        watchdogs.append(watchdog)
        watchdog.start()

    deps.request_shutdown = request_shutdown
    try:
        server.run()
    finally:
        # Once run() has returned no executor thread is left to hold the process.
        for watchdog in watchdogs:
            watchdog.cancel()
    if not server.started:
        return STARTUP_FAILURE
    return exit_codes[0] if exit_codes else 0


def main(serve_deps: Callable[[WorkerDeps, str, int], int] = serve) -> None:
    settings = get_worker_settings()
    configure_logging(settings.log_level)
    exit_code = serve_deps(build_deps(settings), settings.worker_bind_host, settings.worker_port)
    if exit_code:
        sys.exit(exit_code)


if __name__ == "__main__":  # pragma: no cover
    main()
