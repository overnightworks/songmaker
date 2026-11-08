from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import partial
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from acestep_engine.progress import AceStepPhase
from acestep_engine.thread_handoff import acquire_in_thread
from acestep_worker.clock import utcnow
from acestep_worker.models import (
    TaskErrorKind,
    TaskKind,
    TaskResult,
    TaskSnapshot,
    TaskState,
    WorkerTaskEvent,
)

log = logging.getLogger(__name__)

TERMINAL_RETENTION_SECONDS = 60.0
_TERMINAL_STATES: frozenset[TaskState] = frozenset({"done", "error"})


@dataclass
class _Task:
    task_id: str
    kind: TaskKind
    state: TaskState = "pending"
    progress: float = 0.0
    phase: AceStepPhase | None = None
    current_epoch: int | None = None
    train_epochs: int | None = None
    training_started_at: datetime | None = None
    result: TaskResult | None = None
    error: str | None = None
    error_kind: TaskErrorKind | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    terminal_at: datetime | None = None
    # Never part of the snapshot: only the store knows where a result lives.
    result_file: Path | None = None
    subscribers: list[asyncio.Queue[WorkerTaskEvent]] = field(default_factory=list)

    def snapshot(self) -> TaskSnapshot:
        return TaskSnapshot(
            task_id=self.task_id,
            kind=self.kind,
            state=self.state,
            progress=self.progress,
            phase=self.phase,
            current_epoch=self.current_epoch,
            train_epochs=self.train_epochs,
            training_started_at=self.training_started_at,
            result=self.result,
            error=self.error,
            error_kind=self.error_kind,
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


class ResultDiscard(Enum):
    UNKNOWN_TASK = "unknown_task"
    REMOVED = "removed"
    KEPT = "kept"


def _removed(path: Path | None) -> bool:
    """Remove a result file; a failure is logged and the caller keeps the file recorded."""
    if path is None:
        return True
    try:
        path.unlink(missing_ok=True)
    except OSError:
        log.warning("Failed to remove task result %s", path.name, exc_info=True)
        return False
    return True


def _close(handle: BinaryIO) -> None:
    handle.close()


class TaskStore:
    def __init__(self, retention_seconds: float = TERMINAL_RETENTION_SECONDS) -> None:
        self._tasks: dict[str, _Task] = {}
        self._lock = asyncio.Lock()
        self._retention = retention_seconds

    async def create(
        self,
        kind: TaskKind,
        *,
        train_epochs: int | None = None,
        phase: AceStepPhase | None = None,
    ) -> str:
        if kind != "train_lora" and train_epochs is not None:
            raise ValueError("Only LoRA training tasks have epochs")
        if kind != "generate" and phase is not None:
            raise ValueError("Only generation tasks have phases")
        task_id = f"{kind[:3]}-{uuid4().hex[:12]}"
        async with self._lock:
            self._tasks[task_id] = _Task(
                task_id=task_id,
                kind=kind,
                phase=phase,
                current_epoch=0 if train_epochs is not None else None,
                train_epochs=train_epochs,
            )
        return task_id

    async def mark_running(self, task_id: str) -> None:
        await self._update(task_id, state="running")

    async def mark_training_started(self, task_id: str) -> None:
        await self._update(task_id, training_started_at=utcnow())

    async def update_progress(
        self,
        task_id: str,
        progress: float,
        *,
        phase: AceStepPhase | None = None,
        current_epoch: int | None = None,
    ) -> None:
        await self._update(
            task_id,
            progress=progress,
            phase=phase,
            current_epoch=current_epoch,
        )

    async def complete(
        self, task_id: str, result: TaskResult, *, result_file: Path | None = None,
    ) -> None:
        await self._update(
            task_id, state="done", progress=1.0, result=result, terminal=True,
            result_file=result_file,
        )

    async def fail(
        self, task_id: str, message: str, *, error_kind: TaskErrorKind | None = None,
    ) -> None:
        await self._update(
            task_id, state="error", error=message, error_kind=error_kind, terminal=True,
        )

    async def _update(
        self,
        task_id: str,
        *,
        state: TaskState | None = None,
        progress: float | None = None,
        phase: AceStepPhase | None = None,
        current_epoch: int | None = None,
        training_started_at: datetime | None = None,
        result: TaskResult | None = None,
        error: str | None = None,
        error_kind: TaskErrorKind | None = None,
        terminal: bool = False,
        result_file: Path | None = None,
    ) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            if state is not None:
                task.state = state
            if progress is not None:
                task.progress = progress
            if phase is not None:
                task.phase = phase
            if current_epoch is not None:
                task.current_epoch = current_epoch
            if training_started_at is not None:
                task.training_started_at = training_started_at
            if result is not None:
                task.result = result
            if result_file is not None:
                task.result_file = result_file
            if error is not None:
                task.error = error
                task.error_kind = error_kind
            task.updated_at = utcnow()
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

    async def open_result(self, task_id: str) -> BinaryIO | None:
        """Open the file this store recorded for a finished task; no caller names a path.

        The open happens under the lock a removal takes, so a later DELETE or sweep cannot
        cut the returned handle: the file's bytes live until the handle closes.
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.result_file is None:
                return None
            try:
                return await acquire_in_thread(partial(task.result_file.open, "rb"), _close)
            except FileNotFoundError:
                return None

    async def discard_result(self, task_id: str) -> ResultDiscard:
        """Remove a task's result file; a failed removal keeps it recorded for a retry."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return ResultDiscard.UNKNOWN_TASK
            if not _removed(task.result_file):
                return ResultDiscard.KEPT
            task.result_file = None
            return ResultDiscard.REMOVED

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
        cutoff = utcnow()
        async with self._lock:
            to_drop = [
                tid
                for tid, task in self._tasks.items()
                if task.terminal_at is not None
                and (cutoff - task.terminal_at).total_seconds() > self._retention
            ]
            # A record whose file would not go stays, so the next sweep retries the removal.
            removed = [tid for tid in to_drop if _removed(self._tasks[tid].result_file)]
            for tid in removed:
                del self._tasks[tid]
        return len(removed)

    async def sweep_terminal_tasks(
        self, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    ) -> None:
        while True:
            await sleep(self._retention)
            try:
                await self.cleanup_terminal()
            except Exception:
                log.exception("Terminal task sweep failed")
