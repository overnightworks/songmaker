"""A finished task's result file: where it is written and how music fetches and frees it."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from acestep_worker.task_store import TaskStore


def write_result_file(output_root: Path, task_id: str, content: bytes) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    result_file = output_root / f"{task_id}-{uuid4().hex[:8]}.wav"
    result_file.write_bytes(content)
    return result_file


def register_result_routes(router: APIRouter, task_store: TaskStore) -> None:
    """Serve and free a task's result file; the file comes only from the store's own record."""

    async def get_result(task_id: str) -> FileResponse:
        result_file = await task_store.result_file(task_id)
        if result_file is None or not result_file.is_file():
            raise HTTPException(status_code=404, detail=f"No result for task: {task_id}")
        return FileResponse(result_file, media_type="audio/wav")

    async def discard_result(task_id: str) -> None:
        if not await task_store.discard_result(task_id):
            raise HTTPException(status_code=404, detail=f"Unknown task: {task_id}")

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
        responses={404: {"description": "Task does not exist"}},
    )
