"""Scheduler — routes generation jobs to ACE-Step workers.

Stateless picker that lives inside the music-worker arq job. Reads worker
identity from PG and ephemeral state from Redis, atomically claims a slot
via INCR queue_depth, then dispatches via HTTP/SSE to the chosen worker.

The scheduler does not commit DB or own any persistent state — it's a
pure dispatch layer between ``run_generation_job`` and the worker pool.

If the SSE connection drops mid-generation, the scheduler reconnects to
the same task_id (the worker's task store survives across reconnects)
with exponential backoff up to ``MAX_SSE_RECONNECTS``. The worker keeps
generating regardless of whether the scheduler is currently subscribed,
so a transient network blip never wastes a 10-minute generation.

For the tradeoffs and failure modes, see plans/acestep-worker-pool.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, is_dataclass

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
)
from songmaker_cli.db.queries import list_worker_identities
from songmaker_cli.internal_api import INTERNAL_TOKEN_ENV, INTERNAL_TOKEN_HEADER

log = logging.getLogger(__name__)

ProgressCallback = Callable[[float], Awaitable[None] | None]
HeartbeatCallback = Callable[[], Awaitable[None] | None]


class NoCapacityError(RuntimeError):
    """Raised when no online worker can serve the requested model."""


class WorkerTaskFailed(RuntimeError):
    """Raised when the worker emits an `error` SSE event."""


class GenerationTaskResultDTO(BaseModel):
    mode: str
    audio_path: str
    seed: int
    cot_caption: str = ""
    cot_lyrics: str = ""


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
        if state is None:
            continue
        queue_depth = await read_queue_depth(redis, ident.id)
        online.append(
            _PickedWorker(
                id=ident.id,
                host=ident.host,
                port=ident.port,
                loaded_modes=list(state.get("loaded", [])),
                queue_depth=queue_depth,
            ),
        )
    return online


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


def _internal_headers() -> dict[str, str]:
    return {INTERNAL_TOKEN_HEADER: os.environ.get(INTERNAL_TOKEN_ENV, "")}


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


async def consume_task_stream(
    worker: _PickedWorker,
    task_id: str,
    *,
    on_progress: ProgressCallback | None = None,
    on_heartbeat: HeartbeatCallback | None = None,
    options: DispatchOptions = DispatchOptions(),
) -> GenerationTaskResultDTO:
    """Subscribe to ``/tasks/{id}/stream``. Reconnect on transport drop.

    Returns when the worker emits ``done``. Raises ``WorkerTaskFailed`` on
    ``error`` events. Raises the underlying httpx error after exhausting
    ``max_sse_reconnects``.
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
                            await _maybe_invoke(on_heartbeat)
                            if event_type == "done":
                                result_payload = data.get("result") or {}
                                try:
                                    return GenerationTaskResultDTO.model_validate(
                                        result_payload,
                                    )
                                except ValidationError as exc:
                                    raise WorkerTaskFailed(
                                        f"Worker returned invalid result: {exc}",
                                    ) from exc
                            if event_type == "error":
                                message = data.get("error") or "worker error"
                                raise WorkerTaskFailed(message)
                            if event_type == "progress":
                                fraction = float(data.get("progress", 0.0))
                                await _maybe_invoke(on_progress, fraction)
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
