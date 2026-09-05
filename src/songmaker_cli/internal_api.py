"""Internal API — endpoints called by trusted peer containers (workers).

Mounted under ``/api/internal/``. All endpoints require the ``X-Internal-Token``
header to match ``SONGMAKER_INTERNAL_TOKEN``. The reverse proxy MUST NOT
expose ``/api/internal/*`` to the public internet — see ``docs/security.md``.
"""

from __future__ import annotations

import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from songmaker_cli.api_models import WorkerRegisterRequest, WorkerRegisterResponse
from songmaker_cli.app_context import get_db_session
from songmaker_cli.db.queries import register_worker
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

INTERNAL_TOKEN_HEADER = "X-Internal-Token"  # nosec B105


def verify_internal_token(
    x_internal_token: str = Header(..., alias=INTERNAL_TOKEN_HEADER),
) -> None:
    expected = get_settings().songmaker_internal_token.get_secret_value()
    if not expected:
        raise HTTPException(503, "Internal API not configured")
    if not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(401, "Invalid internal token")


router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(verify_internal_token)],
)


@router.post("/workers/register")
def register_worker_endpoint(
    req: WorkerRegisterRequest,
    db: Annotated[Session, Depends(get_db_session)],
) -> WorkerRegisterResponse:
    worker = register_worker(
        db,
        worker_id=req.worker_id,
        host=req.host,
        port=req.port,
        gpu_id=req.gpu_id,
        vram_total_gb=req.vram_total_gb,
    )
    db.commit()
    log.info("Worker registered: %s @ %s:%d", req.worker_id, req.host, req.port)
    return WorkerRegisterResponse(
        worker_id=worker.id,
        registered_at=worker.registered_at.isoformat(),
    )
