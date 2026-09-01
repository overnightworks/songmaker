"""Job status, streaming, and cancellation API endpoints."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from songmaker_cli.api_models import JobResponse
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.auth import ROLE_ADMIN
from songmaker_cli.constants import (
    JOB_ACTIVE_STATUSES,
    JOB_TERMINAL_STATUSES,
    SSE_HEARTBEAT_COMMENT,
    SSE_HEARTBEAT_SECONDS,
    SSE_POLL_INTERVAL_SECONDS,
    AuditAction,
    JobStatus,
    ResourceType,
)
from songmaker_cli.db.models import Job
from songmaker_cli.db.queries import get_job, get_queue_position, record_audit, update_job_status
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

router = APIRouter()


@router.get("/jobs/{job_id}")
def api_get_job(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> JobResponse:
    job = _check_job_access(session, job_id, user)
    return JobResponse.from_orm(job, queue_position=get_queue_position(session, job))


@router.get("/jobs/{job_id}/stream")
async def api_stream_job(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> StreamingResponse:
    _check_job_access(session, job_id, user)
    return StreamingResponse(
        _job_event_generator(ctx, job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _job_event_generator(ctx: AppContext, job_id: str) -> AsyncGenerator[str, None]:
    previous_status: str | None = None
    previous_progress: float | None = None
    last_emit = monotonic()
    try:
        while True:
            with ctx.db() as db_session:
                job = get_job(db_session, job_id)
                if not job:
                    return
                response = JobResponse.from_orm(job)

            status_changed = (
                response.status != previous_status
                or response.progress != previous_progress
            )
            if status_changed:
                previous_status = response.status
                previous_progress = response.progress
                yield f"data: {json.dumps(response.model_dump())}\n\n"
                last_emit = monotonic()
            elif monotonic() - last_emit >= SSE_HEARTBEAT_SECONDS:
                yield SSE_HEARTBEAT_COMMENT
                last_emit = monotonic()

            if response.status in JOB_TERMINAL_STATUSES:
                return

            await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        return


@router.post("/jobs/{job_id}/cancel")
def api_cancel_job(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> JobResponse:
    job = _check_job_access(session, job_id, user)
    if job.status not in JOB_ACTIVE_STATUSES:
        raise HTTPException(409, "Only queued or running jobs can be cancelled")
    if not update_job_status(session, job_id, JobStatus.CANCELLED):
        raise HTTPException(409, "Only queued or running jobs can be cancelled")
    record_audit(session, user.id, AuditAction.CANCEL, ResourceType.JOB, job_id)
    session.commit()
    job = get_job(session, job_id)
    return JobResponse.from_orm(job)


def _check_job_access(session: Session, job_id: str, user: AuthenticatedUser) -> Job:
    job = get_job(session, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if user.role != ROLE_ADMIN and job.user_id != user.id:
        raise HTTPException(404, "Job not found")
    return job
