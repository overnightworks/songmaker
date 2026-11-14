"""Admin API endpoints — voices, workers, model registry, generation retention."""

from __future__ import annotations

import asyncio
import logging
from typing import Final

import httpx
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy.orm import Session
from webauth.ports import AuthenticatedUser

from songmaker_cli.acestep_state import (
    read_download_in_progress,
    read_queue_depth,
    read_worker_state,
    worker_is_online,
)
from songmaker_cli.agent.mcp import Exclusion, exclude_route
from songmaker_cli.api_models import (
    AdminUserLoraResponse,
    EvictModelOnWorkerRequest,
    GenerationRetentionReportResponse,
    JobResponse,
    LoadModelOnWorkerRequest,
    ModelAvailability,
    PinModelOnWorkerRequest,
    RegistryModelResponse,
    RegistryResponse,
    StatusResponse,
    UnpinModelOnWorkerRequest,
    WorkerEphemeralState,
    WorkerIdentity,
    WorkerInfo,
    WorkerPoolResponse,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.arq_pool import get_arq_pool_dep
from songmaker_cli.auth_dependencies import (
    require_admin,
)
from songmaker_cli.constants import MODEL_CONFIG_PATHS, AuditAction, ResourceType
from songmaker_cli.db.queries.auth import (
    record_audit,
)
from songmaker_cli.db.queries.loras import list_user_loras_for_admin
from songmaker_cli.db.queries.workers import get_worker_identity, list_worker_identities
from songmaker_cli.job_types import JobFunction, JobStatus
from songmaker_cli.refusals import Refusal
from songmaker_cli.scheduler import worker_request_headers, worker_response_cause
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

JOB_QUEUE_UNAVAILABLE_DETAIL: Final = "Job queue unavailable"
_RELAYED_WORKER_STATUSES: Final = frozenset({400, 409})


def _require_known_model_mode(mode: str) -> None:
    if mode not in MODEL_CONFIG_PATHS:
        raise Refusal(400, "adminRefusal.unknownModelMode", mode=mode)


def _worker_not_found(worker_id: str) -> Refusal:
    return Refusal(404, "workerRefusal.notFound", workerId=worker_id)


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/voices", openapi_extra=exclude_route(Exclusion.ADMIN))
def list_voices_endpoint(
    db: Session = Depends(get_db_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> list[AdminUserLoraResponse]:
    return [
        AdminUserLoraResponse.from_orm(lora, owner_username)
        for lora, owner_username in list_user_loras_for_admin(db)
    ]


def _derive_worker_status(state: WorkerEphemeralState | None) -> str:
    if state is None or state.gpu_healthy is not True:
        return "offline"
    if state.target_loading:
        return "loading"
    return "online"


def _loaded_modes(state: WorkerEphemeralState) -> list[str]:
    return [detail.mode for detail in state.loaded]


def _state_from_dict(
    state: dict | None,
    queue_depth: int = 0,
    worker_id: str | None = None,
) -> WorkerEphemeralState | None:
    if state is None:
        return None
    try:
        return WorkerEphemeralState.model_validate({**state, "queue_depth": queue_depth})
    except ValidationError:
        log.warning(
            "Ignoring invalid heartbeat from worker %s", worker_id or "unknown", exc_info=True,
        )
        return None


async def _post_to_worker(
    host: str, port: int, path: str, json_body: dict | None = None,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=30) as client:
        return await client.post(
            f"http://{host}:{port}{path}",  # NOSONAR(S5332) Compose network only.
            json=json_body,
            headers=worker_request_headers(),
        )


@router.get("/workers", openapi_extra=exclude_route(Exclusion.ADMIN))
async def list_workers_endpoint(
    db: Session = Depends(get_db_session),
    pool: ArqRedis = Depends(get_arq_pool_dep),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> WorkerPoolResponse:
    workers = list_worker_identities(db)
    infos: list[WorkerInfo] = []
    for w in workers:
        state = await read_worker_state(pool, w.id)
        queue_depth = await read_queue_depth(pool, w.id)
        parsed_state = _state_from_dict(state, queue_depth, worker_id=w.id)
        infos.append(
            WorkerInfo(
                identity=WorkerIdentity.from_orm(w),
                state=parsed_state,
                status=_derive_worker_status(parsed_state),
            ),
        )
    return WorkerPoolResponse(workers=infos)


@router.get("/registry", openapi_extra=exclude_route(Exclusion.ADMIN))
async def get_registry_endpoint(
    db: Session = Depends(get_db_session),
    pool: ArqRedis = Depends(get_arq_pool_dep),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> RegistryResponse:
    workers = list_worker_identities(db)
    states = await _registry_worker_states(pool, workers)
    return RegistryResponse(models=_registry_models(states))


async def _registry_worker_states(
    pool: ArqRedis,
    workers: list,
) -> dict[str, WorkerEphemeralState | None]:
    return {
        worker.id: _state_from_dict(
            await read_worker_state(pool, worker.id), worker_id=worker.id,
        )
        for worker in workers
    }


def _registry_models(
    states: dict[str, WorkerEphemeralState | None],
) -> list[RegistryModelResponse]:
    any_worker_online = any(_derive_worker_status(state) != "offline" for state in states.values())
    downloaded_modes = {
        mode for state in states.values() if state is not None for mode in state.available_modes
    }
    return [
        _registry_model(mode, states, any_worker_online, downloaded_modes)
        for mode in MODEL_CONFIG_PATHS
    ]


def _registry_model(
    mode: str,
    states: dict[str, WorkerEphemeralState | None],
    any_worker_online: bool,
    downloaded_modes: set[str],
) -> RegistryModelResponse:
    loaded_on = sorted(
        worker_id for worker_id, state in states.items()
        if state is not None and mode in _loaded_modes(state)
    )
    loading_on = sorted(
        worker_id for worker_id, state in states.items()
        if state is not None and state.target_loading == mode
    )
    if not any_worker_online:
        availability: ModelAvailability = "unknown_no_worker"
    elif mode in downloaded_modes:
        availability = "downloaded"
    else:
        availability = "not_downloaded"
    return RegistryModelResponse(
        mode=mode,
        availability=availability,
        loaded_on=loaded_on,
        loading_on=loading_on,
    )


@router.post(
    "/workers/{worker_id}/load_model",
    responses={
        400: {"description": "Model load request is invalid"},
        404: {"description": "Worker does not exist"},
        503: {"description": "Worker is unavailable"},
    },
    openapi_extra=exclude_route(Exclusion.ADMIN),
)
async def load_model_on_worker_endpoint(
    worker_id: str,
    req: LoadModelOnWorkerRequest,
    db: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> JobResponse:
    from songmaker_cli.arq_pool import get_arq_pool
    from songmaker_cli.constants import ARQ_MUSIC_QUEUE_NAME
    from songmaker_cli.db.queries.jobs import (
        JobStatusUpdate,
        create_job,
        get_queue_position,
        update_job_status,
    )

    worker = get_worker_identity(db, worker_id)
    if worker is None:
        raise _worker_not_found(worker_id)
    _require_known_model_mode(req.mode)

    job = create_job(db, JobFunction.LOAD_MODEL_ON_WORKER, user_id=admin.id)
    db.commit()

    try:
        pool = get_arq_pool()
        await pool.enqueue_job(
            JobFunction.LOAD_MODEL_ON_WORKER, job.id, worker_id, req.mode,
            _queue_name=ARQ_MUSIC_QUEUE_NAME,
        )
    except ConnectionError:
        update_job_status(
            db, job.id, JobStatusUpdate(JobStatus.FAILED, error=JOB_QUEUE_UNAVAILABLE_DETAIL),
        )
        db.commit()
        raise Refusal(503, "jobRefusal.queueUnavailable")

    return JobResponse.from_orm(job, queue_position=get_queue_position(db, job))


async def _command_worker_model(db: Session, worker_id: str, path: str, mode: str) -> None:
    """Post a model command to a worker; its 400 or 409 refusal reaches the admin with its words."""
    worker = get_worker_identity(db, worker_id)
    if worker is None:
        raise _worker_not_found(worker_id)
    _require_known_model_mode(mode)

    try:
        response = await _post_to_worker(worker.host, worker.port, path, {"mode": mode})
    except httpx.HTTPError as exc:
        raise Refusal(502, "workerRefusal.unreachable", reason=str(exc))
    if response.status_code >= 400:
        cause = worker_response_cause(response)
        refusal = Refusal(502, "workerRefusal.relayed", cause=cause)
        if response.status_code in _RELAYED_WORKER_STATUSES:
            refusal.status_code = response.status_code
        raise refusal


@router.post(
    "/workers/{worker_id}/evict_model",
    responses={
        400: {"description": "Model eviction request is invalid"},
        404: {"description": "Worker does not exist"},
        409: {"description": "Model cannot be evicted"},
        502: {"description": "Worker rejected model eviction"},
    },
    openapi_extra=exclude_route(Exclusion.ADMIN),
)
async def evict_model_on_worker_endpoint(
    worker_id: str,
    req: EvictModelOnWorkerRequest,
    db: Session = Depends(get_db_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> StatusResponse:
    await _command_worker_model(db, worker_id, "/evict_model", req.mode)
    return StatusResponse(status="ok")


@router.post(
    "/workers/{worker_id}/pin_model",
    responses={
        400: {"description": "Model pin request is invalid"},
        404: {"description": "Worker does not exist"},
        409: {"description": "Model cannot be pinned"},
        502: {"description": "Worker rejected model pinning"},
    },
    openapi_extra=exclude_route(Exclusion.ADMIN),
)
async def pin_model_on_worker_endpoint(
    worker_id: str,
    req: PinModelOnWorkerRequest,
    db: Session = Depends(get_db_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> StatusResponse:
    await _command_worker_model(db, worker_id, "/pin_model", req.mode)
    return StatusResponse(status="ok")


@router.post(
    "/workers/{worker_id}/unpin_model",
    responses={
        400: {"description": "Model unpin request is invalid"},
        404: {"description": "Worker does not exist"},
        409: {"description": "Model cannot be unpinned"},
        502: {"description": "Worker rejected model unpinning"},
    },
    openapi_extra=exclude_route(Exclusion.ADMIN),
)
async def unpin_model_on_worker_endpoint(
    worker_id: str,
    req: UnpinModelOnWorkerRequest,
    db: Session = Depends(get_db_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> StatusResponse:
    await _command_worker_model(db, worker_id, "/unpin_model", req.mode)
    return StatusResponse(status="ok")


@router.post(
    "/workers/{worker_id}/restart",
    responses={
        404: {"description": "Worker does not exist"},
        502: {"description": "Worker restart failed"},
    },
    openapi_extra=exclude_route(Exclusion.ADMIN),
)
async def restart_worker_endpoint(
    worker_id: str,
    db: Session = Depends(get_db_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> StatusResponse:
    worker = get_worker_identity(db, worker_id)
    if worker is None:
        raise _worker_not_found(worker_id)

    try:
        response = await _post_to_worker(worker.host, worker.port, "/restart")
    except httpx.HTTPError as exc:
        # Restart asks the running worker process to end itself; nothing is listening to ask.
        raise Refusal(502, "workerRefusal.notResponding", workerId=worker_id) from exc
    if response.status_code >= 400:
        raise Refusal(502, "workerRefusal.returnedStatus", status=str(response.status_code))
    return StatusResponse(status="restarting")


@router.post(
    "/registry/{mode}/download",
    responses={
        400: {"description": "Requested model mode is invalid"},
        409: {"description": "Model is already downloaded or downloading"},
        503: {"description": "Model registry or job queue is unavailable"},
    },
    openapi_extra=exclude_route(Exclusion.ADMIN),
)
async def download_model_endpoint(
    mode: str,
    admin: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db_session),
    pool: ArqRedis = Depends(get_arq_pool_dep),
) -> JobResponse:
    from songmaker_cli.arq_pool import get_arq_pool
    from songmaker_cli.constants import ARQ_MUSIC_QUEUE_NAME
    from songmaker_cli.db.queries.jobs import (
        JobStatusUpdate,
        create_job,
        get_queue_position,
        update_job_status,
    )

    _require_known_model_mode(mode)

    workers = list_worker_identities(db)
    online_states: dict[str, dict | None] = {}
    for w in workers:
        online_states[w.id] = await read_worker_state(pool, w.id)

    if not any(worker_is_online(state) for state in online_states.values()):
        raise Refusal(503, "adminRefusal.noOnlineWorkers")

    downloaded_union: set[str] = set()
    for state in online_states.values():
        if state is not None:
            downloaded_union.update(state.get("available_modes", []))
    if mode in downloaded_union:
        raise Refusal(409, "adminRefusal.alreadyDownloaded", mode=mode)

    in_progress = await read_download_in_progress(pool, mode)
    if in_progress is not None:
        raise Refusal(409, "adminRefusal.alreadyDownloading", mode=mode, jobId=in_progress)

    job = create_job(db, JobFunction.DOWNLOAD_MODEL_ON_WORKER, user_id=admin.id)
    db.commit()

    try:
        arq_pool = get_arq_pool()
        await arq_pool.enqueue_job(
            JobFunction.DOWNLOAD_MODEL_ON_WORKER, job.id, mode,
            _queue_name=ARQ_MUSIC_QUEUE_NAME,
        )
    except ConnectionError:
        update_job_status(
            db, job.id, JobStatusUpdate(JobStatus.FAILED, error=JOB_QUEUE_UNAVAILABLE_DETAIL),
        )
        db.commit()
        raise Refusal(503, "jobRefusal.queueUnavailable")

    return JobResponse.from_orm(job, queue_position=get_queue_position(db, job))


def _retention_report_response(
    report, *, dry_run: bool,
) -> GenerationRetentionReportResponse:
    from songmaker_cli.cleanup import DAILY_CLEANUP_HOUR_UTC

    settings = get_settings()
    return GenerationRetentionReportResponse(
        archived_ids=report.archived_ids,
        deleted_ids=report.deleted_ids,
        archived_count=report.archived_count,
        deleted_count=report.deleted_count,
        retention_days=settings.generation_retention_days,
        hard_delete_days=settings.final_deletion_days,
        scheduled_hour_utc=DAILY_CLEANUP_HOUR_UTC,
        dry_run=dry_run,
    )


@router.get("/generation-retention/preview", openapi_extra=exclude_route(Exclusion.ADMIN))
async def generation_retention_preview(
    ctx: AppContext = Depends(get_app_context),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> GenerationRetentionReportResponse:
    from songmaker_cli.cleanup import run_generation_retention

    report = await asyncio.to_thread(
        run_generation_retention, ctx.db, ctx.audio_dir, dry_run=True,
    )
    return _retention_report_response(report, dry_run=True)


@router.post("/generation-retention/run", openapi_extra=exclude_route(Exclusion.ADMIN))
async def generation_retention_run(
    ctx: AppContext = Depends(get_app_context),
    admin: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db_session),
) -> GenerationRetentionReportResponse:
    from songmaker_cli.cleanup import run_generation_retention

    report = await asyncio.to_thread(
        run_generation_retention, ctx.db, ctx.audio_dir, dry_run=False,
    )
    record_audit(
        db, admin.id, AuditAction.HARD_DELETE, ResourceType.GENERATION,
        detail=f"retention: archived={report.archived_count}, deleted={report.deleted_count}",
    )
    db.commit()
    return _retention_report_response(report, dry_run=False)
