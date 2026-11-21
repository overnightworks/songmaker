from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from songmaker_acestep_engine.constants import MODEL_CONFIG_PATHS
from songmaker_acestep_worker.child_tasks import settle_child_task
from songmaker_acestep_worker.models import DownloadTaskResult
from songmaker_acestep_worker.settings import get_worker_settings
from songmaker_acestep_worker.task_store import TaskStore

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

    hf = get_worker_settings().hf_token
    token = hf.get_secret_value() if hf else None
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
        await asyncio.sleep(interval)
        actual = directory_size_bytes(target_dir)
        ratio = min(actual / expected_size, 0.99) if expected_size > 0 else 0.0
        await task_store.update_progress(task_id, ratio)


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
            DownloadTaskResult(mode=mode, size_bytes=actual_size),
        )
    except Exception as exc:
        log.exception("Download failed for mode %s", mode)
        await task_store.fail(task_id, f"{type(exc).__name__}: {exc}")
    finally:
        progress_task.cancel()
        await settle_child_task(progress_task)


_background_tasks: set[asyncio.Task[None]] = set()


def spawn_background(coro: Awaitable[None]) -> asyncio.Task[None]:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


# One entry per (checkpoint directory, mode) while its download runs. The snapshot transfer is a
# thread that cannot be cancelled, so a second request for the mode joins the running task.
_running_downloads: dict[tuple[Path, str], asyncio.Future[str]] = {}


async def start_download(
    task_store: TaskStore,
    *,
    mode: str,
    checkpoint_dir: Path,
    download_fn: DownloadFn = hf_snapshot_download,
) -> str:
    """The task id of the download of ``mode``; a download already running for it is joined."""
    key = (checkpoint_dir, mode)
    running = _running_downloads.get(key)
    if running is not None:
        return await running
    reserved: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    _running_downloads[key] = reserved
    try:
        task_id = await task_store.create("download")
    except BaseException:
        del _running_downloads[key]
        reserved.cancel()
        raise
    reserved.set_result(task_id)
    spawn_background(
        run_download(
            task_store,
            task_id,
            mode=mode,
            checkpoint_dir=checkpoint_dir,
            download_fn=download_fn,
        )
    ).add_done_callback(lambda _finished: _running_downloads.pop(key, None))
    return task_id
