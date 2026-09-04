from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from acestep_worker.models import (
    TaskKind,
    TaskResult,
    TaskSnapshot,
    TaskState,
    WorkerTaskEvent,
)

TERMINAL_RETENTION_SECONDS = 60.0
_TERMINAL_STATES: frozenset[TaskState] = frozenset({"done", "error"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _Task:
    task_id: str
    kind: TaskKind
    state: TaskState = "pending"
    progress: float = 0.0
    current_epoch: int | None = None
    train_epochs: int | None = None
    training_started_at: datetime | None = None
    result: TaskResult | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    terminal_at: datetime | None = None
    subscribers: list[asyncio.Queue[WorkerTaskEvent]] = field(default_factory=list)

    def snapshot(self) -> TaskSnapshot:
        return TaskSnapshot(
            task_id=self.task_id,
            kind=self.kind,
            state=self.state,
            progress=self.progress,
            current_epoch=self.current_epoch,
            train_epochs=self.train_epochs,
            training_started_at=self.training_started_at,
            result=self.result,
            error=self.error,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    def to_event(self) -> WorkerTaskEvent:
        snap = self.snapshot().model_dump(mode="json")
        if self.state == "done":
            return WorkerTaskEvent(type="done", data=snap)
        if self.state == "error":
            return WorkerTaskEvent(type="error", data=snap)
        return WorkerTaskEvent(type="progress", data=snap)


class TaskStore:
    def __init__(self, retention_seconds: float = TERMINAL_RETENTION_SECONDS) -> None:
        self._tasks: dict[str, _Task] = {}
        self._lock = asyncio.Lock()
        self._retention = retention_seconds

    async def create(self, kind: TaskKind, *, train_epochs: int | None = None) -> str:
        if kind != "train_lora" and train_epochs is not None:
            raise ValueError("Only LoRA training tasks have epochs")
        task_id = f"{kind[:3]}-{uuid4().hex[:12]}"
        async with self._lock:
            self._tasks[task_id] = _Task(
                task_id=task_id,
                kind=kind,
                current_epoch=0 if train_epochs is not None else None,
                train_epochs=train_epochs,
            )
        return task_id

    async def mark_running(self, task_id: str) -> None:
        await self._update(task_id, state="running")

    async def mark_training_started(self, task_id: str) -> None:
        await self._update(task_id, training_started_at=_now())

    async def update_progress(
        self,
        task_id: str,
        progress: float,
        *,
        current_epoch: int | None = None,
    ) -> None:
        await self._update(
            task_id,
            progress=progress,
            current_epoch=current_epoch,
        )

    async def complete(self, task_id: str, result: TaskResult) -> None:
        await self._update(
            task_id, state="done", progress=1.0, result=result, terminal=True
        )

    async def fail(self, task_id: str, message: str) -> None:
        await self._update(task_id, state="error", error=message, terminal=True)

    async def _update(
        self,
        task_id: str,
        *,
        state: TaskState | None = None,
        progress: float | None = None,
        current_epoch: int | None = None,
        training_started_at: datetime | None = None,
        result: TaskResult | None = None,
        error: str | None = None,
        terminal: bool = False,
    ) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            if state is not None:
                task.state = state
            if progress is not None:
                task.progress = progress
            if current_epoch is not None:
                task.current_epoch = current_epoch
            if training_started_at is not None:
                task.training_started_at = training_started_at
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error
            task.updated_at = _now()
            if terminal:
                task.terminal_at = task.updated_at
            event = task.to_event()
            subscribers = list(task.subscribers)
        for queue in subscribers:
            await queue.put(event)

    async def get(self, task_id: str) -> TaskSnapshot | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            return task.snapshot() if task else None

    async def subscribe(self, task_id: str) -> AsyncIterator[WorkerTaskEvent]:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            queue: asyncio.Queue[WorkerTaskEvent] = asyncio.Queue()
            initial = task.to_event()
            already_terminal = task.state in _TERMINAL_STATES
            task.subscribers.append(queue)

        try:
            yield initial
            if already_terminal:
                return
            while True:
                event = await queue.get()
                yield event
                if event.type in ("done", "error"):
                    return
        finally:
            async with self._lock:
                task = self._tasks.get(task_id)
                if task is not None and queue in task.subscribers:
                    task.subscribers.remove(queue)

    async def cleanup_terminal(self) -> int:
        cutoff = _now()
        async with self._lock:
            to_drop = [
                tid
                for tid, task in self._tasks.items()
                if task.terminal_at is not None
                and (cutoff - task.terminal_at).total_seconds() > self._retention
            ]
            for tid in to_drop:
                del self._tasks[tid]
        return len(to_drop)

    async def size(self) -> int:
        async with self._lock:
            return len(self._tasks)
