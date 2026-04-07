from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from acestep_worker.downloads import (
    directory_size_bytes,
    is_model_downloaded,
    list_available_modes,
    model_dir,
    run_download,
    start_download,
)
from acestep_worker.task_store import TaskStore


def _run(coro):
    return asyncio.run(coro)


def test_model_dir_unknown() -> None:
    assert model_dir(Path("/tmp"), "ghost") is None


def test_model_dir_known(tmp_path: Path) -> None:
    result = model_dir(tmp_path, "sft")
    assert result == tmp_path / "checkpoints" / "acestep-v15-sft"


def test_is_model_downloaded_missing(tmp_path: Path) -> None:
    assert is_model_downloaded(tmp_path, "sft") is False


def test_is_model_downloaded_present(tmp_path: Path) -> None:
    target = tmp_path / "checkpoints" / "acestep-v15-sft"
    target.mkdir(parents=True)
    (target / "config.json").write_text("{}")
    (target / "model.safetensors").write_bytes(b"weights")
    assert is_model_downloaded(tmp_path, "sft") is True


def test_is_model_downloaded_partial_only_config(tmp_path: Path) -> None:
    target = tmp_path / "checkpoints" / "acestep-v15-sft"
    target.mkdir(parents=True)
    (target / "config.json").write_text("{}")
    assert is_model_downloaded(tmp_path, "sft") is False


def test_is_model_downloaded_partial_only_weights(tmp_path: Path) -> None:
    target = tmp_path / "checkpoints" / "acestep-v15-sft"
    target.mkdir(parents=True)
    (target / "model.safetensors").write_bytes(b"weights")
    assert is_model_downloaded(tmp_path, "sft") is False


def test_is_model_downloaded_unknown(tmp_path: Path) -> None:
    assert is_model_downloaded(tmp_path, "ghost") is False


def test_list_available_modes_partial(tmp_path: Path) -> None:
    for mode in ("sft", "turbo"):
        d = tmp_path / "checkpoints" / f"acestep-v15-{mode}"
        d.mkdir(parents=True)
        (d / "config.json").write_text("{}")
        (d / "model.safetensors").write_bytes(b"x")
    available = list_available_modes(tmp_path)
    assert "sft" in available
    assert "turbo" in available
    assert "xl-base" not in available


def test_directory_size_empty(tmp_path: Path) -> None:
    assert directory_size_bytes(tmp_path / "ghost") == 0


def test_directory_size_with_files(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_bytes(b"x" * 100)
    (tmp_path / "b.bin").write_bytes(b"y" * 50)
    assert directory_size_bytes(tmp_path) == 150


def test_start_download_creates_task(tmp_path: Path) -> None:
    async def go():
        store = TaskStore()
        completed = asyncio.Event()

        async def fake_download(repo_id: str, local_dir: Path) -> None:
            local_dir.mkdir(parents=True, exist_ok=True)
            (local_dir / "config.json").write_text(json.dumps({"name": repo_id}))
            (local_dir / "weights.bin").write_bytes(b"x" * 200)
            completed.set()

        task_id = await start_download(
            store,
            mode="sft",
            checkpoint_dir=tmp_path,
            download_fn=fake_download,
        )
        await asyncio.wait_for(completed.wait(), timeout=2.0)
        for _ in range(50):
            snap = await store.get(task_id)
            if snap and snap.state == "done":
                break
            await asyncio.sleep(0.02)
        return await store.get(task_id)

    snap = _run(go())
    assert snap is not None
    assert snap.state == "done"
    assert snap.result is not None
    assert snap.result["mode"] == "sft"
    assert snap.result["size_bytes"] >= 200


def test_run_download_unknown_mode(tmp_path: Path) -> None:
    async def go():
        store = TaskStore()
        task_id = await store.create("download")
        await run_download(
            store,
            task_id,
            mode="ghost",
            checkpoint_dir=tmp_path,
            download_fn=_unused_download,
        )
        return await store.get(task_id)

    snap = _run(go())
    assert snap is not None
    assert snap.state == "error"
    assert "Unknown mode" in (snap.error or "")


async def _unused_download(repo_id: str, local_dir: Path) -> None:
    raise AssertionError("should not be called")


def test_run_download_failure(tmp_path: Path) -> None:
    async def go():
        store = TaskStore()
        task_id = await store.create("download")

        async def failing(repo_id: str, local_dir: Path) -> None:
            raise RuntimeError("network broke")

        await run_download(
            store,
            task_id,
            mode="sft",
            checkpoint_dir=tmp_path,
            download_fn=failing,
        )
        return await store.get(task_id)

    snap = _run(go())
    assert snap is not None
    assert snap.state == "error"
    assert "network broke" in (snap.error or "")


def test_poll_progress_emits_updates(tmp_path: Path) -> None:
    from acestep_worker.downloads import _poll_progress

    async def go():
        store = TaskStore()
        task_id = await store.create("download")
        await store.mark_running(task_id)
        target = tmp_path / "checkpoints" / "x"
        target.mkdir(parents=True)
        (target / "data.bin").write_bytes(b"a" * 50)
        polling = asyncio.create_task(
            _poll_progress(store, task_id, target, expected_size=100, interval=0.01)
        )
        await asyncio.sleep(0.05)
        polling.cancel()
        try:
            await polling
        except asyncio.CancelledError:
            pass
        return await store.get(task_id)

    snap = _run(go())
    assert snap is not None
    assert snap.progress > 0


def test_poll_progress_zero_expected(tmp_path: Path) -> None:
    from acestep_worker.downloads import _poll_progress

    async def go():
        store = TaskStore()
        task_id = await store.create("download")
        await store.mark_running(task_id)
        polling = asyncio.create_task(
            _poll_progress(store, task_id, tmp_path, expected_size=0, interval=0.01)
        )
        await asyncio.sleep(0.03)
        polling.cancel()
        try:
            await polling
        except asyncio.CancelledError:
            pass
        return await store.get(task_id)

    snap = _run(go())
    assert snap is not None
    assert snap.progress == 0.0


def test_spawn_background_keeps_strong_reference() -> None:
    from acestep_worker.downloads import _background_tasks, spawn_background

    async def go():
        async def worker():
            await asyncio.sleep(0)

        task = spawn_background(worker())
        assert task in _background_tasks
        await task
        await asyncio.sleep(0)
        assert task not in _background_tasks

    _run(go())


def test_run_download_real_huggingface_uses_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_snapshot(repo_id: str, local_dir: str, token: str | None = None) -> None:
        captured["repo_id"] = repo_id
        captured["local_dir"] = local_dir
        captured["token"] = token
        Path(local_dir).mkdir(parents=True, exist_ok=True)

    import sys
    import types

    fake_module = types.ModuleType("huggingface_hub")
    fake_module.snapshot_download = fake_snapshot  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_module)
    monkeypatch.setenv("HF_TOKEN", "tk-test")

    from acestep_worker.downloads import hf_snapshot_download

    _run(hf_snapshot_download("ACE-Step/x", tmp_path / "x"))
    assert captured["repo_id"] == "ACE-Step/x"
    assert captured["token"] == "tk-test"
