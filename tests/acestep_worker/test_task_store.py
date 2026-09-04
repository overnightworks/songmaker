from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from acestep_worker.models import GenerationTaskResult
from acestep_worker.task_store import TaskStore, _now


def _run(coro):
    return asyncio.run(coro)


def _generated(audio_path: str = "/x.wav", seed: int = 42) -> GenerationTaskResult:
    return GenerationTaskResult(mode="sft", audio_path=audio_path, seed=seed)


def test_create_returns_unique_ids() -> None:
    async def go() -> tuple[str, str]:
        store = TaskStore()
        a = await store.create("generate")
        b = await store.create("generate")
        return a, b

    a, b = _run(go())
    assert a.startswith("gen-")
    assert b.startswith("gen-")
    assert a != b


def test_create_download_prefix() -> None:
    async def go() -> str:
        store = TaskStore()
        return await store.create("download")

    task_id = _run(go())
    assert task_id.startswith("dow-")


def test_get_returns_snapshot() -> None:
    async def go():
        store = TaskStore()
        task_id = await store.create("generate")
        snap = await store.get(task_id)
        return task_id, snap

    task_id, snap = _run(go())
    assert snap is not None
    assert snap.task_id == task_id
    assert snap.state == "pending"
    assert snap.kind == "generate"


def test_get_unknown_returns_none() -> None:
    async def go():
        store = TaskStore()
        return await store.get("nope")

    assert _run(go()) is None


def test_mark_running_updates_state() -> None:
    async def go():
        store = TaskStore()
        task_id = await store.create("generate")
        await store.mark_running(task_id)
        return await store.get(task_id)

    snap = _run(go())
    assert snap is not None
    assert snap.state == "running"


def test_update_progress() -> None:
    async def go():
        store = TaskStore()
        task_id = await store.create("download")
        await store.update_progress(task_id, 0.42)
        return await store.get(task_id)

    snap = _run(go())
    assert snap is not None
    assert snap.progress == 0.42


def test_training_progress_carries_real_epochs() -> None:
    async def go():
        store = TaskStore()
        task_id = await store.create("train_lora", train_epochs=500)
        await store.update_progress(task_id, 0.34, current_epoch=100)
        return await store.get(task_id)

    snapshot = _run(go())

    assert snapshot is not None
    assert snapshot.current_epoch == 100
    assert snapshot.train_epochs == 500


def test_complete_terminal() -> None:
    async def go():
        store = TaskStore()
        task_id = await store.create("generate")
        await store.complete(task_id, _generated())
        return await store.get(task_id)

    snap = _run(go())
    assert snap is not None
    assert snap.state == "done"
    assert snap.progress == 1.0
    assert snap.result == _generated()


def test_done_event_carries_the_result_as_json() -> None:
    async def go():
        store = TaskStore()
        task_id = await store.create("generate")
        events = []

        async def consume():
            async for ev in store.subscribe(task_id):
                events.append(ev)

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0)
        await store.complete(task_id, _generated(audio_path="/out.wav", seed=99))
        await consumer
        return events

    events = _run(go())
    assert events[-1].data["result"] == {
        "mode": "sft",
        "audio_path": "/out.wav",
        "seed": 99,
        "cot_caption": "",
        "cot_lyrics": "",
        "delivered_batch_size": None,
    }


def test_fail_terminal() -> None:
    async def go():
        store = TaskStore()
        task_id = await store.create("generate")
        await store.fail(task_id, "boom")
        return await store.get(task_id)

    snap = _run(go())
    assert snap is not None
    assert snap.state == "error"
    assert snap.error == "boom"


def test_update_unknown_raises() -> None:
    async def go():
        store = TaskStore()
        await store.mark_running("ghost")

    with pytest.raises(KeyError):
        _run(go())


def test_subscribe_replays_initial_then_terminal() -> None:
    async def go():
        store = TaskStore()
        task_id = await store.create("generate")
        events = []

        async def consume():
            async for ev in store.subscribe(task_id):
                events.append(ev)

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0)
        await store.mark_running(task_id)
        await store.update_progress(task_id, 0.5)
        await store.complete(task_id, _generated())
        await consumer
        return events

    events = _run(go())
    assert len(events) >= 2
    assert events[-1].type == "done"
    assert events[-1].data["state"] == "done"


def test_subscribe_unknown_raises() -> None:
    async def go():
        store = TaskStore()
        async for _ in store.subscribe("ghost"):
            pass

    with pytest.raises(KeyError):
        _run(go())


def test_subscribe_already_terminal_yields_only_initial() -> None:
    async def go():
        store = TaskStore()
        task_id = await store.create("generate")
        await store.complete(task_id, _generated())
        events = []
        async for ev in store.subscribe(task_id):
            events.append(ev)
        return events

    events = _run(go())
    assert len(events) == 1
    assert events[0].type == "done"


def test_subscribe_already_failed_yields_only_initial() -> None:
    async def go():
        store = TaskStore()
        task_id = await store.create("download")
        await store.fail(task_id, "nope")
        events = []
        async for ev in store.subscribe(task_id):
            events.append(ev)
        return events

    events = _run(go())
    assert len(events) == 1
    assert events[0].type == "error"


def test_subscribe_progress_then_done() -> None:
    async def go():
        store = TaskStore()
        task_id = await store.create("download")
        events = []

        async def consume():
            async for ev in store.subscribe(task_id):
                events.append(ev)
                if ev.type == "done":
                    return

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0)
        await store.update_progress(task_id, 0.3)
        await store.complete(task_id, _generated())
        await consumer
        return events

    events = _run(go())
    types = [e.type for e in events]
    assert "progress" in types
    assert types[-1] == "done"


def test_subscribe_cleanup_on_unsubscribe() -> None:
    async def go():
        store = TaskStore()
        task_id = await store.create("generate")

        async def consume_one():
            async for ev in store.subscribe(task_id):
                _ = ev
                return

        await consume_one()
        task = store._tasks[task_id]
        return task.subscribers

    subscribers = _run(go())
    assert subscribers == []


def test_cleanup_terminal_drops_old() -> None:
    async def go():
        store = TaskStore(retention_seconds=0.0)
        task_id = await store.create("generate")
        await store.complete(task_id, _generated())
        store._tasks[task_id].terminal_at = _now() - timedelta(seconds=10)
        dropped = await store.cleanup_terminal()
        size = await store.size()
        return dropped, size

    dropped, size = _run(go())
    assert dropped == 1
    assert size == 0


def test_cleanup_terminal_keeps_running() -> None:
    async def go():
        store = TaskStore()
        await store.create("generate")
        dropped = await store.cleanup_terminal()
        size = await store.size()
        return dropped, size

    dropped, size = _run(go())
    assert dropped == 0
    assert size == 1
