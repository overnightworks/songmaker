from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from acestep_engine.constants import MODEL_CONFIG_PATHS
from acestep_worker.task_store import TaskStore

log = logging.getLogger(__name__)

PROGRESS_POLL_SECONDS = 2.0

ESTIMATED_MODEL_SIZE_BYTES: dict[str, int] = {
    "turbo": 6_500_000_000,
    "sft": 6_500_000_000,
    "xl-turbo": 13_000_000_000,
    "xl-sft": 13_000_000_000,
    "xl-base": 13_000_000_000,
}

REQUIRED_CONFIG: str = "config.json"
SINGLE_WEIGHTS_FILENAME: str = "model.safetensors"
SHARDED_INDEX_FILENAME: str = "model.safetensors.index.json"

DownloadFn = Callable[[str, Path], Awaitable[None]]


def model_dir(checkpoint_dir: Path, mode: str) -> Path | None:
    config_path = MODEL_CONFIG_PATHS.get(mode)
    if config_path is None:
        return None
    return checkpoint_dir / "checkpoints" / config_path


def is_model_downloaded(checkpoint_dir: Path, mode: str) -> bool:
    target = model_dir(checkpoint_dir, mode)
    if target is None or not target.exists():
        return False
    if not (target / REQUIRED_CONFIG).exists():
        return False
    if (target / SINGLE_WEIGHTS_FILENAME).exists():
        return True
    return (target / SHARDED_INDEX_FILENAME).exists()


def list_available_modes(checkpoint_dir: Path) -> list[str]:
    return [mode for mode in MODEL_CONFIG_PATHS if is_model_downloaded(checkpoint_dir, mode)]


def directory_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


async def hf_snapshot_download(repo_id: str, local_dir: Path) -> None:
    from huggingface_hub import snapshot_download

    token = os.environ.get("HF_TOKEN")
    await asyncio.to_thread(
        snapshot_download,
        repo_id=repo_id,
        local_dir=str(local_dir),
        token=token,
    )


async def _poll_progress(
    task_store: TaskStore,
    task_id: str,
    target_dir: Path,
    expected_size: int,
    interval: float = PROGRESS_POLL_SECONDS,
) -> None:
    while True:
        try:
            await asyncio.sleep(interval)
            actual = directory_size_bytes(target_dir)
            ratio = min(actual / expected_size, 0.99) if expected_size > 0 else 0.0
            await task_store.update_progress(task_id, ratio)
        except asyncio.CancelledError:
            return


async def run_download(
    task_store: TaskStore,
    task_id: str,
    *,
    mode: str,
    checkpoint_dir: Path,
    download_fn: DownloadFn = hf_snapshot_download,
) -> None:
    config_path = MODEL_CONFIG_PATHS.get(mode)
    if config_path is None:
        await task_store.fail(task_id, f"Unknown mode: {mode}")
        return
    target_dir = checkpoint_dir / "checkpoints" / config_path
    expected_size = ESTIMATED_MODEL_SIZE_BYTES.get(mode, 0)
    await task_store.mark_running(task_id)
    progress_task = asyncio.create_task(
        _poll_progress(task_store, task_id, target_dir, expected_size)
    )
    try:
        await download_fn(f"ACE-Step/{config_path}", target_dir)
        actual_size = directory_size_bytes(target_dir)
        await task_store.complete(
            task_id,
            {"mode": mode, "size_bytes": actual_size},
        )
    except Exception as exc:
        log.exception("Download failed for mode %s", mode)
        await task_store.fail(task_id, f"{type(exc).__name__}: {exc}")
    finally:
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass


_background_tasks: set[asyncio.Task[None]] = set()


def spawn_background(coro: Awaitable[None]) -> asyncio.Task[None]:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def start_download(
    task_store: TaskStore,
    *,
    mode: str,
    checkpoint_dir: Path,
    download_fn: DownloadFn = hf_snapshot_download,
) -> str:
    task_id = await task_store.create("download")
    spawn_background(
        run_download(
            task_store,
            task_id,
            mode=mode,
            checkpoint_dir=checkpoint_dir,
            download_fn=download_fn,
        )
    )
    return task_id
