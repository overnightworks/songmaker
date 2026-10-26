"""Scheduler — routes generation jobs to ACE-Step workers.

Stateless picker that lives inside the music-worker arq job. Reads worker
identity from PG and ephemeral state from Redis, picks the worker with the
lowest queue_depth, then dispatches via HTTP/SSE to the chosen worker. The
generation admission Lua script atomically rejects a LoRA hold and increments
the selected worker's queue depth. The generation job owns that admission for
its complete take series and releases it during final cleanup.

The scheduler does not commit DB or own any persistent state — it's a
pure dispatch layer between ``run_generation_job`` and the worker pool.

If an SSE transport connection drops mid-generation, the scheduler reconnects
to the same task_id (the worker's task store survives across reconnects) with
exponential backoff up to ``MAX_SSE_RECONNECTS``. An SSE read timeout is not
retried: it means the worker stream went silent and must fail the job promptly.
The worker keeps generating through a transient transport drop regardless of
whether the scheduler is currently subscribed, so reconnecting does not waste
a 10-minute generation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict, dataclass, is_dataclass
from typing import Final

import httpx
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from sqlalchemy.orm import Session, sessionmaker

from acestep_engine.constants import MODE_NOT_LOADED_DETAIL
from acestep_engine.models import AceStepConfig
from acestep_engine.progress import AceStepPhase
from songmaker_cli.acestep_state import (
    admit_generation as admit_generation_occupancy,
)
from songmaker_cli.acestep_state import (
    gpu_hold_key,
    read_queue_depth,
    read_worker_state,
    worker_is_online,
)
from songmaker_cli.api_models.workers import WorkerEphemeralState
from songmaker_cli.constants import (
    ACESTEP_SSE_CONNECT_TIMEOUT_SECONDS,
    ACESTEP_SSE_READ_TIMEOUT_SECONDS,
    GENERATE_LOAD_MODEL_TIMEOUT_SECONDS,
    GENERATE_SUBMIT_TIMEOUT_SECONDS,
    INTERNAL_TOKEN_HEADER,
    JOB_ERROR_WORKER_STREAM_SILENT,
)
from songmaker_cli.db.queries.workers import list_worker_identities
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

ProgressCallback = Callable[[float], Awaitable[None] | None]
GenerationProgressCallback = Callable[[AceStepPhase, float], Awaitable[None] | None]
ProgressEventHandler = Callable[[dict], Awaitable[None]]
HeartbeatCallback = Callable[[], Awaitable[None] | None]
WORKER_STREAM_WENT_SILENT = JOB_ERROR_WORKER_STREAM_SILENT
WORKER_ERROR_GPU_OUT_OF_MEMORY: Final = "gpu_out_of_memory"
NO_ONLINE_ACESTEP_WORKERS_DETAIL: Final = "No online ACE-Step workers"


class NoCapacityError(RuntimeError):
    """Raised when no online worker can serve the requested model."""


class AllWorkersHeld(RuntimeError):
    """Raised when online workers exist but every one has a LoRA hold."""


class WorkerTaskFailed(RuntimeError):
    """Raised when a worker request or task fails, preserving its cause."""


class WorkerGenerationFailed(WorkerTaskFailed):
    """Raised for a worker ``error`` event, preserving its diagnostic cause."""


class WorkerGpuOutOfMemory(WorkerGenerationFailed):
    """Raised only for the worker's typed GPU-memory failure."""


WorkerErrorClassifier = Callable[[dict], type[WorkerTaskFailed]]


class WorkerGenerationUnavailable(WorkerTaskFailed):
    """Raised when Generate cannot load, reach, or continue using its worker."""


class WorkerModeNotLoaded(WorkerTaskFailed):
    """Raised when ``/generate`` finds the job's mode no longer loaded.

    Another job's ``/load_model`` may evict this job's mode between two of
    its takes, since a mode is only held while a take runs on it.
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


@dataclass
class _PickedWorker:
    """One job's view of a worker: its heartbeat at admission plus the loads this job made."""

    id: str
    host: str
    port: int
    loaded_modes: list[str]
    queue_depth: int

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"  # NOSONAR(S5332) Compose network only.

    def record_loaded(self, mode: str) -> None:
        if mode not in self.loaded_modes:
            self.loaded_modes = [*self.loaded_modes, mode]


@dataclass
class DispatchOptions:
    max_sse_reconnects: int = 5
    load_model_timeout_seconds: float = GENERATE_LOAD_MODEL_TIMEOUT_SECONDS
    generate_submit_timeout_seconds: float = GENERATE_SUBMIT_TIMEOUT_SECONDS
    sse_connect_timeout_seconds: float = ACESTEP_SSE_CONNECT_TIMEOUT_SECONDS
    sse_read_timeout_seconds: float = ACESTEP_SSE_READ_TIMEOUT_SECONDS
    initial_reconnect_backoff_seconds: float = 1.0
    max_reconnect_backoff_seconds: float = 30.0
    transport: httpx.AsyncBaseTransport | None = None


async def _list_online_workers(
    db: Session,
    redis: Redis,
) -> list[_PickedWorker]:
    identities = list_worker_identities(db)
    online: list[_PickedWorker] = []
    for ident in identities:
        state = await read_worker_state(redis, ident.id)
        if not worker_is_online(state):
            continue
        try:
            heartbeat = WorkerEphemeralState.model_validate(state)
        except ValidationError:
            log.warning(
                "Ignoring unreadable ACE-Step worker heartbeat for worker %s",
                ident.id,
                exc_info=True,
            )
            continue
        queue_depth = await read_queue_depth(redis, ident.id)
        online.append(
            _PickedWorker(
                id=ident.id,
                host=ident.host,
                port=ident.port,
                loaded_modes=[model.mode for model in heartbeat.loaded],
                queue_depth=queue_depth,
            ),
        )
    return online


def _pick_from(workers: list[_PickedWorker], target_mode: str) -> _PickedWorker:
    if not workers:
        raise NoCapacityError(NO_ONLINE_ACESTEP_WORKERS_DETAIL)
    loaded = [w for w in workers if target_mode in w.loaded_modes]
    pool = loaded if loaded else workers
    return min(pool, key=lambda w: w.queue_depth)


async def pick_worker(
    db: Session,
    redis: Redis,
    target_mode: str,
) -> _PickedWorker:
    workers = await _list_online_workers(db, redis)
    if not workers:
        raise NoCapacityError(NO_ONLINE_ACESTEP_WORKERS_DETAIL)
    available = [worker for worker in workers if not await redis.exists(gpu_hold_key(worker.id))]
    if not available:
        raise AllWorkersHeld("All online ACE-Step workers are held for LoRA training")
    return _pick_from(available, target_mode)


async def pick_any_online_worker(
    db: Session,
    redis: Redis,
) -> _PickedWorker:
    workers = await _list_online_workers(db, redis)
    if not workers:
        raise NoCapacityError(NO_ONLINE_ACESTEP_WORKERS_DETAIL)
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
            event_type = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    if event_type is None or not data_lines:
        return None
    try:
        data = json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return event_type, data


def worker_response_cause(response: httpx.Response) -> str:
    if not response.text.strip():
        return f"Worker returned {response.status_code} with no detail"
    try:
        body = json.loads(response.text)
    except json.JSONDecodeError:
        return response.text
    if isinstance(body, dict) and isinstance(body.get("detail"), str):
        return body["detail"]
    return response.text


async def _ensure_loaded(
    worker: _PickedWorker,
    target_mode: str,
    options: DispatchOptions,
    on_progress: GenerationProgressCallback | None = None,
) -> None:
    if target_mode in worker.loaded_modes:
        return
    await _load_model(worker, target_mode, options, on_progress)


async def _load_model(
    worker: _PickedWorker,
    target_mode: str,
    options: DispatchOptions,
    on_progress: GenerationProgressCallback | None,
) -> None:
    log.info(
        "Worker %s does not have %s loaded — issuing /load_model",
        worker.id,
        target_mode,
    )
    await _maybe_invoke(on_progress, AceStepPhase.LOADING_MODEL, 0.0)
    async with httpx.AsyncClient(
        timeout=options.load_model_timeout_seconds,
        transport=options.transport,
    ) as client:
        try:
            resp = await client.post(
                f"{worker.base_url}/load_model",
                json={"mode": target_mode},
                headers=_internal_headers(),
            )
        except httpx.TransportError as exc:
            raise WorkerGenerationUnavailable(str(exc)) from exc
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise WorkerGenerationUnavailable(worker_response_cause(resp)) from exc
    worker.record_loaded(target_mode)


async def _submit_generation(
    worker: _PickedWorker,
    ace_config: AceStepConfig,
    target_mode: str,
    options: DispatchOptions,
) -> str:
    config_payload = asdict(ace_config) if is_dataclass(ace_config) else dict(ace_config)
    async with httpx.AsyncClient(
        timeout=options.generate_submit_timeout_seconds,
        transport=options.transport,
    ) as client:
        try:
            resp = await client.post(
                f"{worker.base_url}/generate",
                json={"mode": target_mode, "config": config_payload},
                headers=_internal_headers(),
            )
        except httpx.TransportError as exc:
            raise WorkerGenerationUnavailable(str(exc)) from exc
        if _answers_mode_not_loaded(resp, target_mode):
            raise WorkerModeNotLoaded(worker_response_cause(resp))
        resp.raise_for_status()
        return resp.json()["task_id"]


def _answers_mode_not_loaded(response: httpx.Response, mode: str) -> bool:
    if response.status_code != httpx.codes.CONFLICT:
        return False
    return worker_response_cause(response) == MODE_NOT_LOADED_DETAIL.format(mode=mode)


async def _iterate_task_events(
    worker: _PickedWorker,
    task_id: str,
    *,
    options: DispatchOptions = DispatchOptions(),
) -> AsyncIterator[tuple[str, dict]]:
    """Yield (event_type, data) tuples from a worker's /tasks/{id}/stream.

    Reconnects on transport drops with exponential backoff up to
    ``options.max_sse_reconnects``. ``httpx.ReadTimeout`` is deliberately
    raised without retrying before the broader ``httpx.TransportError`` catch:
    it is a transport-error subclass, but for this stream it means the worker
    went silent. Stops yielding after a ``done`` or ``error`` event (both ARE
    yielded so the caller can validate or surface them). Raises the underlying
    httpx error after exhausting the reconnect budget.
    """
    reconnects = 0
    while True:
        try:
            async for event_type, data in _worker_task_events(worker, task_id, options):
                yield event_type, data
                if event_type in ("done", "error"):
                    return
            return
        except httpx.ReadTimeout:
            raise
        except (httpx.TransportError, httpx.RemoteProtocolError) as exc:
            reconnects += 1
            backoff = _sse_reconnect_delay(worker, task_id, reconnects, options, exc)
            await asyncio.sleep(backoff)


async def _worker_task_events(
    worker: _PickedWorker,
    task_id: str,
    options: DispatchOptions,
) -> AsyncIterator[tuple[str, dict]]:
    timeout = httpx.Timeout(
        connect=options.sse_connect_timeout_seconds,
        read=options.sse_read_timeout_seconds,
        write=options.sse_connect_timeout_seconds,
        pool=options.sse_connect_timeout_seconds,
    )
    async with (
        httpx.AsyncClient(timeout=timeout, transport=options.transport) as client,
        client.stream(
            "GET",
            f"{worker.base_url}/tasks/{task_id}/stream",
            headers=_internal_headers(),
        ) as response,
    ):
        response.raise_for_status()
        buffer = ""
        async for chunk in response.aiter_text():
            buffer += chunk
            while "\n\n" in buffer:
                raw, buffer = buffer.split("\n\n", 1)
                parsed = _parse_sse_event(raw)
                if parsed is not None:
                    yield parsed


def _sse_reconnect_delay(
    worker: _PickedWorker,
    task_id: str,
    reconnects: int,
    options: DispatchOptions,
    error: Exception,
) -> float:
    if reconnects > options.max_sse_reconnects:
        log.error("SSE reconnect budget exhausted for task %s on %s", task_id, worker.id)
        raise error
    backoff = min(
        options.initial_reconnect_backoff_seconds * (2 ** (reconnects - 1)),
        options.max_reconnect_backoff_seconds,
    )
    log.warning(
        "SSE drop on %s task %s (attempt %d/%d): %s — reconnecting in %.1fs",
        worker.id,
        task_id,
        reconnects,
        options.max_sse_reconnects,
        error,
        backoff,
    )
    return backoff


async def _consume_task_stream[_TaskResultT: BaseModel](
    worker: _PickedWorker,
    task_id: str,
    *,
    result_type: type[_TaskResultT],
    invalid_result_label: str,
    error_classifier: WorkerErrorClassifier,
    on_progress_event: ProgressEventHandler,
    silence_exception_type: type[WorkerTaskFailed] = WorkerTaskFailed,
    on_heartbeat: HeartbeatCallback | None = None,
    options: DispatchOptions = DispatchOptions(),
) -> _TaskResultT:
    """Consume a worker task stream. Returns the validated ``result_type`` DTO.

    ``error_classifier`` selects the exception for a validated non-empty
    error event. Generation consumes typed causes; other task kinds retain
    their own failure class. The diagnostic message is retained for logging.

    Raises ``WorkerProtocolError`` when an SSE event violates the wire
    contract: a ``done`` event missing ``result``, an ``error`` event
    missing ``error``, or an ``error`` event whose ``error`` field is empty
    (the worker is required to always attach a cause).
    """
    try:
        async for event_type, data in _iterate_task_events(worker, task_id, options=options):
            await _maybe_invoke(on_heartbeat)
            result = await _consume_stream_event(
                event_type,
                data,
                result_type=result_type,
                invalid_result_label=invalid_result_label,
                error_classifier=error_classifier,
                on_progress_event=on_progress_event,
            )
            if result is not None:
                return result
    except httpx.ReadTimeout as exc:
        raise silence_exception_type(WORKER_STREAM_WENT_SILENT) from exc
    raise WorkerTaskFailed("SSE stream ended without done/error event")


async def _consume_stream_event[_TaskResultT: BaseModel](
    event_type: str,
    data: dict,
    *,
    result_type: type[_TaskResultT],
    invalid_result_label: str,
    error_classifier: WorkerErrorClassifier,
    on_progress_event: ProgressEventHandler,
) -> _TaskResultT | None:
    if event_type == "progress":
        await on_progress_event(data)
        return None
    if event_type == "done":
        return _validate_task_result(data, result_type, invalid_result_label)
    if event_type == "error":
        _raise_worker_event_error(data, error_classifier)
    return None


def _plain_progress_events(on_progress: ProgressCallback | None) -> ProgressEventHandler:
    async def handle(data: dict) -> None:
        await _maybe_invoke(on_progress, float(data.get("progress", 0.0)))

    return handle


def _generation_progress_events(
    on_progress: GenerationProgressCallback | None,
) -> ProgressEventHandler:
    """Hand on a generate task's phase and fraction.

    An event without a known phase or without a progress value is logged and
    dropped rather than failing the take: the generation keeps running and
    the job keeps its last value.
    """

    async def handle(data: dict) -> None:
        try:
            phase = AceStepPhase(data.get("phase"))
        except ValueError:
            log.warning("Worker generate progress event without a known phase: %r", data)
            return
        if "progress" not in data:
            log.warning("Worker generate progress event without a progress value: %r", data)
            return
        await _maybe_invoke(on_progress, phase, float(data["progress"]))

    return handle


def _validate_task_result[_TaskResultT: BaseModel](
    data: dict,
    result_type: type[_TaskResultT],
    invalid_result_label: str,
) -> _TaskResultT:
    if "result" not in data:
        raise WorkerProtocolError("Worker done event missing 'result' field")
    try:
        return result_type.model_validate(data["result"])
    except ValidationError as exc:
        raise WorkerTaskFailed(
            f"Worker returned {invalid_result_label}: {exc}",
        ) from exc


def _generation_error_class(data: dict) -> type[WorkerTaskFailed]:
    if data.get("error_kind") == WORKER_ERROR_GPU_OUT_OF_MEMORY:
        return WorkerGpuOutOfMemory
    return WorkerGenerationFailed


def _raise_worker_event_error(
    data: dict,
    error_classifier: WorkerErrorClassifier,
) -> None:
    if "error" not in data:
        raise WorkerProtocolError("Worker error event missing 'error' field")
    message = data["error"]
    if not message:
        log.warning("Worker error event has empty 'error' field")
        raise WorkerProtocolError("Worker error event has an empty 'error' field")
    raise error_classifier(data)(message)


async def consume_task_stream(
    worker: _PickedWorker,
    task_id: str,
    *,
    on_progress: GenerationProgressCallback | None = None,
    on_heartbeat: HeartbeatCallback | None = None,
    options: DispatchOptions = DispatchOptions(),
) -> GenerationTaskResultDTO:
    """Consume a worker generate task stream. Returns the validated DTO.

    Raises ``WorkerTaskFailed`` on error events or invalid result payloads.
    Raises ``WorkerGenerationUnavailable`` on silence or exhausted reconnects.
    """
    try:
        return await _consume_task_stream(
            worker,
            task_id,
            result_type=GenerationTaskResultDTO,
            invalid_result_label="invalid result",
            error_classifier=_generation_error_class,
            silence_exception_type=WorkerGenerationUnavailable,
            on_progress_event=_generation_progress_events(on_progress),
            on_heartbeat=on_heartbeat,
            options=options,
        )
    except httpx.TransportError as exc:
        raise WorkerGenerationUnavailable(str(exc)) from exc


async def consume_download_task_stream(
    worker: _PickedWorker,
    task_id: str,
    *,
    on_progress: ProgressCallback | None = None,
    on_heartbeat: HeartbeatCallback | None = None,
    options: DispatchOptions = DispatchOptions(),
) -> DownloadTaskResultDTO:
    """Consume a worker download task stream. Returns the validated DTO.

    Raises ``WorkerTaskFailed`` on error events, invalid payloads, or silence.
    Exhausted reconnects retain the transport error; only generation streams
    translate silence and exhausted reconnects to ``WorkerGenerationUnavailable``.
    """
    return await _consume_task_stream(
        worker,
        task_id,
        result_type=DownloadTaskResultDTO,
        invalid_result_label="invalid download result",
        error_classifier=lambda _data: WorkerTaskFailed,
        on_progress_event=_plain_progress_events(on_progress),
        on_heartbeat=on_heartbeat,
        options=options,
    )


async def admit_generation_worker(
    *,
    target_mode: str,
    redis: Redis,
    db_factory: sessionmaker[Session],
) -> _PickedWorker:
    with db_factory() as session:
        worker = await pick_worker(session, redis, target_mode)
    if not await admit_generation_occupancy(redis, worker.id):
        raise AllWorkersHeld("ACE-Step worker became held before generation admission")
    return worker


async def dispatch_generation_on_worker(
    *,
    worker: _PickedWorker,
    ace_config: AceStepConfig,
    target_mode: str,
    on_progress: GenerationProgressCallback | None = None,
    on_heartbeat: HeartbeatCallback | None = None,
    options: DispatchOptions = DispatchOptions(),
) -> GenerationTaskResultDTO:
    await _ensure_loaded(worker, target_mode, options, on_progress)
    try:
        task_id = await _submit_generation(worker, ace_config, target_mode, options)
    except WorkerModeNotLoaded:
        log.info("Worker %s no longer has %s loaded — reloading it once", worker.id, target_mode)
        await _load_model(worker, target_mode, options, on_progress)
        try:
            task_id = await _submit_generation(worker, ace_config, target_mode, options)
        except WorkerModeNotLoaded as exc:
            raise WorkerGenerationUnavailable(str(exc)) from exc
    return await consume_task_stream(
        worker,
        task_id,
        on_progress=on_progress,
        on_heartbeat=on_heartbeat,
        options=options,
    )
