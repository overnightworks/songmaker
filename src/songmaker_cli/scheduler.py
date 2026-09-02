"""Scheduler — routes generation jobs to ACE-Step workers.

Stateless picker that lives inside the music-worker arq job. Reads worker
identity from PG and ephemeral state from Redis, picks the worker with the
lowest queue_depth, then dispatches via HTTP/SSE to the chosen worker.
Picking is check-then-act, not an atomic claim: ``pick_worker`` reads each
worker's queue_depth and ``incr_queue_depth`` bumps the chosen worker's
counter as a separate later step, so two concurrent picks can briefly land
on the same worker before either increment is visible to the other. INCR is
only a load counter for the next picker, not a lock.

The scheduler does not commit DB or own any persistent state — it's a
pure dispatch layer between ``run_generation_job`` and the worker pool.

If the SSE connection drops mid-generation, the scheduler reconnects to
the same task_id (the worker's task store survives across reconnects)
with exponential backoff up to ``MAX_SSE_RECONNECTS``. The worker keeps
generating regardless of whether the scheduler is currently subscribed,
so a transient network blip never wastes a 10-minute generation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from sqlalchemy.orm import Session, sessionmaker

from acestep_engine.models import AceStepConfig
from songmaker_cli.acestep_state import (
    decr_queue_depth,
    incr_queue_depth,
    read_queue_depth,
    read_worker_state,
    worker_is_online,
)
from songmaker_cli.db.queries import list_worker_identities
from songmaker_cli.internal_api import INTERNAL_TOKEN_HEADER
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

ProgressCallback = Callable[[float], Awaitable[None] | None]
HeartbeatCallback = Callable[[], Awaitable[None] | None]


class NoCapacityError(RuntimeError):
    """Raised when no online worker can serve the requested model."""


class WorkerTaskFailed(RuntimeError):
    """Raised when the worker emits an `error` SSE event."""


class WorkerGenerationFailed(WorkerTaskFailed):
    """Raised when a worker reports that its generate task failed.

    Its message is ACE-Step's own cause for the failure and is written
    for the operator: the job layer stores it and the UI shows it
    verbatim, so nothing generic may be raised as this type.
    """


class WorkerProtocolError(WorkerTaskFailed):
    """Raised when a worker SSE event violates the wire contract.

    Subclasses :class:`WorkerTaskFailed` so existing ``except`` blocks
    continue to work, but the specific class lets diagnostics distinguish
    "the worker reported a real task failure" from "the worker sent a
    malformed event that should never happen". A protocol error always
    indicates a bug in the worker — not a transient failure.
    """


class DownloadTaskResultDTO(BaseModel):
    mode: str
    size_bytes: int


class GenerationTaskResultDTO(BaseModel):
    mode: str
    audio_path: str
    seed: int
    cot_caption: str = ""
    cot_lyrics: str = ""
    delivered_batch_size: int | None = None


_TaskResultT = TypeVar("_TaskResultT", bound=BaseModel)


@dataclass(frozen=True)
class _PickedWorker:
    id: str
    host: str
    port: int
    loaded_modes: list[str]
    queue_depth: int

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass
class DispatchOptions:
    max_sse_reconnects: int = 5
    load_model_timeout_seconds: float = 600.0
    generate_submit_timeout_seconds: float = 30.0
    sse_connect_timeout_seconds: float = 10.0
    sse_read_timeout_seconds: float | None = None
    initial_reconnect_backoff_seconds: float = 1.0
    max_reconnect_backoff_seconds: float = 30.0


async def _list_online_workers(
    db: Session, redis: Redis,
) -> list[_PickedWorker]:
    identities = list_worker_identities(db)
    online: list[_PickedWorker] = []
    for ident in identities:
        state = await read_worker_state(redis, ident.id)
        if not worker_is_online(state):
            continue
        queue_depth = await read_queue_depth(redis, ident.id)
        online.append(
            _PickedWorker(
                id=ident.id,
                host=ident.host,
                port=ident.port,
                loaded_modes=_extract_loaded_modes(state.get("loaded", [])),
                queue_depth=queue_depth,
            ),
        )
    return online


def _extract_loaded_modes(raw_loaded: Any) -> list[str]:
    if not raw_loaded:
        return []
    modes: list[str] = []
    for entry in raw_loaded:
        if isinstance(entry, dict) and "mode" in entry:
            modes.append(str(entry["mode"]))
        elif isinstance(entry, str):
            modes.append(entry)
    return modes


def _pick_from(workers: list[_PickedWorker], target_mode: str) -> _PickedWorker:
    if not workers:
        raise NoCapacityError("No online ACE-Step workers")
    loaded = [w for w in workers if target_mode in w.loaded_modes]
    pool = loaded if loaded else workers
    return min(pool, key=lambda w: w.queue_depth)


async def pick_worker(
    db: Session, redis: Redis, target_mode: str,
) -> _PickedWorker:
    return _pick_from(await _list_online_workers(db, redis), target_mode)


async def pick_any_online_worker(
    db: Session, redis: Redis,
) -> _PickedWorker:
    workers = await _list_online_workers(db, redis)
    if not workers:
        raise NoCapacityError("No online ACE-Step workers")
    return min(workers, key=lambda w: w.id)


def _internal_headers() -> dict[str, str]:
    return {
        INTERNAL_TOKEN_HEADER: get_settings().songmaker_internal_token.get_secret_value(),
    }


async def _maybe_invoke(callback: Callable | None, *args) -> None:
    if callback is None:
        return
    result = callback(*args)
    if asyncio.iscoroutine(result):
        await result


def _parse_sse_event(buffer: str) -> tuple[str, dict] | None:
    event_type: str | None = None
    data_lines: list[str] = []
    for line in buffer.splitlines():
        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].strip())
    if event_type is None or not data_lines:
        return None
    try:
        data = json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return event_type, data


async def _ensure_loaded(
    worker: _PickedWorker, target_mode: str, options: DispatchOptions,
) -> None:
    if target_mode in worker.loaded_modes:
        return
    log.info(
        "Worker %s does not have %s loaded — issuing /load_model",
        worker.id, target_mode,
    )
    async with httpx.AsyncClient(timeout=options.load_model_timeout_seconds) as client:
        resp = await client.post(
            f"{worker.base_url}/load_model",
            json={"mode": target_mode},
            headers=_internal_headers(),
        )
        resp.raise_for_status()


async def _submit_generation(
    worker: _PickedWorker,
    ace_config: AceStepConfig,
    target_mode: str,
    options: DispatchOptions,
) -> str:
    config_payload = asdict(ace_config) if is_dataclass(ace_config) else dict(ace_config)
    async with httpx.AsyncClient(timeout=options.generate_submit_timeout_seconds) as client:
        resp = await client.post(
            f"{worker.base_url}/generate",
            json={"mode": target_mode, "config": config_payload},
            headers=_internal_headers(),
        )
        resp.raise_for_status()
        return resp.json()["task_id"]


async def _iterate_task_events(
    worker: _PickedWorker,
    task_id: str,
    *,
    options: DispatchOptions = DispatchOptions(),
) -> AsyncIterator[tuple[str, dict]]:
    """Yield (event_type, data) tuples from a worker's /tasks/{id}/stream.

    Reconnects on transport drop with exponential backoff up to
    ``options.max_sse_reconnects``. Stops yielding after a ``done`` or
    ``error`` event (both ARE yielded so the caller can validate or
    surface them). Raises the underlying httpx error after exhausting
    the reconnect budget.
    """
    reconnects = 0
    timeout = httpx.Timeout(
        connect=options.sse_connect_timeout_seconds,
        read=options.sse_read_timeout_seconds,
        write=options.sse_connect_timeout_seconds,
        pool=options.sse_connect_timeout_seconds,
    )
    while True:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "GET",
                    f"{worker.base_url}/tasks/{task_id}/stream",
                    headers=_internal_headers(),
                ) as resp:
                    resp.raise_for_status()
                    buffer = ""
                    async for chunk in resp.aiter_text():
                        buffer += chunk
                        while "\n\n" in buffer:
                            raw, buffer = buffer.split("\n\n", 1)
                            parsed = _parse_sse_event(raw)
                            if parsed is None:
                                continue
                            event_type, data = parsed
                            yield event_type, data
                            if event_type in ("done", "error"):
                                return
            return
        except (httpx.TransportError, httpx.RemoteProtocolError) as exc:
            reconnects += 1
            if reconnects > options.max_sse_reconnects:
                log.error(
                    "SSE reconnect budget exhausted for task %s on %s",
                    task_id, worker.id,
                )
                raise
            backoff = min(
                options.initial_reconnect_backoff_seconds * (2 ** (reconnects - 1)),
                options.max_reconnect_backoff_seconds,
            )
            log.warning(
                "SSE drop on %s task %s (attempt %d/%d): %s — reconnecting in %.1fs",
                worker.id, task_id, reconnects, options.max_sse_reconnects, exc, backoff,
            )
            await asyncio.sleep(backoff)


async def _consume_task_stream(
    worker: _PickedWorker,
    task_id: str,
    *,
    result_type: type[_TaskResultT],
    invalid_result_label: str,
    error_exception_type: type[WorkerTaskFailed],
    on_progress: ProgressCallback | None = None,
    on_heartbeat: HeartbeatCallback | None = None,
    options: DispatchOptions = DispatchOptions(),
) -> _TaskResultT:
    """Consume a worker task stream. Returns the validated ``result_type`` DTO.

    ``error_exception_type`` is raised for a real (non-empty) ``error``
    event, so a caller can distinguish a generation failure — whose message
    is ACE-Step's own cause, shown verbatim to the user — from any other
    task kind's failure.

    Raises ``WorkerProtocolError`` when an SSE event violates the wire
    contract: a ``done`` event missing ``result``, an ``error`` event
    missing ``error``, or an ``error`` event whose ``error`` field is empty
    (the worker is required to always attach a cause).
    """
    async for event_type, data in _iterate_task_events(worker, task_id, options=options):
        await _maybe_invoke(on_heartbeat)
        if event_type == "progress":
            fraction = float(data.get("progress", 0.0))
            await _maybe_invoke(on_progress, fraction)
        elif event_type == "done":
            if "result" not in data:
                raise WorkerProtocolError(
                    "Worker done event missing 'result' field",
                )
            try:
                return result_type.model_validate(data["result"])
            except ValidationError as exc:
                raise WorkerTaskFailed(
                    f"Worker returned {invalid_result_label}: {exc}",
                ) from exc
        elif event_type == "error":
            if "error" not in data:
                raise WorkerProtocolError(
                    "Worker error event missing 'error' field",
                )
            message = data["error"]
            if not message:
                log.warning("Worker error event has empty 'error' field")
                raise WorkerProtocolError(
                    "Worker error event has an empty 'error' field",
                )
            raise error_exception_type(message)
    raise WorkerTaskFailed("SSE stream ended without done/error event")


async def consume_task_stream(
    worker: _PickedWorker,
    task_id: str,
    *,
    on_progress: ProgressCallback | None = None,
    on_heartbeat: HeartbeatCallback | None = None,
    options: DispatchOptions = DispatchOptions(),
) -> GenerationTaskResultDTO:
    """Consume a worker generate task stream. Returns the validated DTO.

    Raises ``WorkerTaskFailed`` on error events or invalid result payloads.
    """
    return await _consume_task_stream(
        worker, task_id,
        result_type=GenerationTaskResultDTO,
        invalid_result_label="invalid result",
        error_exception_type=WorkerGenerationFailed,
        on_progress=on_progress,
        on_heartbeat=on_heartbeat,
        options=options,
    )


async def consume_download_task_stream(
    worker: _PickedWorker,
    task_id: str,
    *,
    on_progress: ProgressCallback | None = None,
    on_heartbeat: HeartbeatCallback | None = None,
    options: DispatchOptions = DispatchOptions(),
) -> DownloadTaskResultDTO:
    """Consume a worker download task stream. Returns the validated DTO.

    Raises ``WorkerTaskFailed`` on error events or invalid result payloads.
    """
    return await _consume_task_stream(
        worker, task_id,
        result_type=DownloadTaskResultDTO,
        invalid_result_label="invalid download result",
        error_exception_type=WorkerTaskFailed,
        on_progress=on_progress,
        on_heartbeat=on_heartbeat,
        options=options,
    )


async def dispatch_generation(
    *,
    ace_config: AceStepConfig,
    target_mode: str,
    on_progress: ProgressCallback | None = None,
    on_heartbeat: HeartbeatCallback | None = None,
    redis: Redis,
    db_factory: sessionmaker[Session],
    options: DispatchOptions = DispatchOptions(),
) -> GenerationTaskResultDTO:
    with db_factory() as session:
        worker = await pick_worker(session, redis, target_mode)

    await incr_queue_depth(redis, worker.id)
    try:
        await _ensure_loaded(worker, target_mode, options)
        task_id = await _submit_generation(worker, ace_config, target_mode, options)
        return await consume_task_stream(
            worker,
            task_id,
            on_progress=on_progress,
            on_heartbeat=on_heartbeat,
            options=options,
        )
    finally:
        await decr_queue_depth(redis, worker.id)
