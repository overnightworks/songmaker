"""The worker lifespan keeps the terminal-task sweep running for as long as the app serves."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from test_wrapper import _make_deps

from acestep_worker.clock import utcnow
from acestep_worker.models import GenerationTaskResult
from acestep_worker.task_store import TaskStore
from acestep_worker.wrapper import create_app, lifespan

_MAX_YIELDS = 100


def _sweep_loops_running() -> list[asyncio.Task[None]]:
    return [
        task
        for task in asyncio.all_tasks()
        if getattr(task.get_coro(), "__qualname__", "")
        == TaskStore.sweep_terminal_tasks.__qualname__
    ]


def test_lifespan_sweeps_expired_terminal_tasks_until_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def go() -> None:
        store = TaskStore(retention_seconds=0.0)
        expired = await store.create("generate")
        await store.complete(expired, GenerationTaskResult(mode="sft", audio_path="/x.wav", seed=1))
        later = utcnow() + timedelta(seconds=1)
        monkeypatch.setattr("acestep_worker.task_store.utcnow", lambda: later)

        deps, _ = _make_deps(tmp_path)
        deps.task_store = store
        async with lifespan(create_app(deps)):
            for _ in range(_MAX_YIELDS):
                if await store.get(expired) is None:
                    break
                await asyncio.sleep(0)
            assert await store.get(expired) is None
            assert _sweep_loops_running()

        assert not _sweep_loops_running()

    asyncio.run(go())
