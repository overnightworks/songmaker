"""A finished task's result file: where it is written and how music fetches and frees it."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Final
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from acestep_worker.task_store import ResultDiscard, TaskStore

_CHUNK_BYTES: Final = 64 * 1024


def write_result_file(output_root: Path, task_id: str, content: bytes) -> Path:
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        result_file = output_root / f"{task_id}-{uuid4().hex[:8]}.wav"
        result_file.write_bytes(content)
    except OSError as exc:
        # The task's error crosses the wire: keep the errno, drop the worker's file name.
        raise OSError(exc.errno, exc.strerror) from exc
    return result_file


def _chunks(take: BinaryIO) -> Iterator[bytes]:
    while chunk := take.read(_CHUNK_BYTES):
        yield chunk


class _TakeResponse(StreamingResponse):
    """Streams an open take and closes it however delivery ends: done, disconnect or error.

    Starlette never closes an interrupted body iterator, so the handle would otherwise wait
    for finalization and keep an already removed file's storage alive.
    """

    def __init__(self, take: BinaryIO) -> None:
        self._take = take
        super().__init__(
            _chunks(take), media_type="audio/wav",
            headers={"Content-Length": str(os.fstat(take.fileno()).st_size)},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await asyncio.to_thread(self._take.close)


def register_result_routes(router: APIRouter, task_store: TaskStore) -> None:
    """Serve and free a task's result file; the file comes only from the store's own record."""

    async def get_result(task_id: str) -> StreamingResponse:
        take = await task_store.open_result(task_id)
        if take is None:
            raise HTTPException(status_code=404, detail=f"No result for task: {task_id}")
        return _TakeResponse(take)

    async def discard_result(task_id: str) -> None:
        match await task_store.discard_result(task_id):
            case ResultDiscard.UNKNOWN_TASK:
                raise HTTPException(status_code=404, detail=f"Unknown task: {task_id}")
            case ResultDiscard.KEPT:
                raise HTTPException(
                    status_code=500,
                    detail="The result file could not be removed; the expiry sweep retries",
                )
            case ResultDiscard.REMOVED:
                return

    router.add_api_route(
        "/tasks/{task_id}/result",
        get_result,
        methods=["GET"],
        responses={404: {"description": "Task has no result file"}},
    )
    router.add_api_route(
        "/tasks/{task_id}/result",
        discard_result,
        methods=["DELETE"],
        status_code=204,
        responses={
            404: {"description": "Task does not exist"},
            500: {"description": "Result file could not be removed"},
        },
    )
