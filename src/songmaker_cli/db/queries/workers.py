"""Query functions for ACE-Step worker identity."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from songmaker_cli.db.models import AceStepWorker


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def register_worker(
    session: Session,
    *,
    worker_id: str,
    host: str,
    port: int,
    gpu_id: int | None,
    vram_total_gb: float | None,
) -> AceStepWorker:
    existing = session.get(AceStepWorker, worker_id)
    if existing is not None:
        existing.host = host
        existing.port = port
        existing.gpu_id = gpu_id
        existing.vram_total_gb = vram_total_gb
        existing.last_register_at = _utcnow()
        session.flush()
        return existing
    worker = AceStepWorker(
        id=worker_id,
        host=host,
        port=port,
        gpu_id=gpu_id,
        vram_total_gb=vram_total_gb,
    )
    session.add(worker)
    session.flush()
    return worker


def get_worker_identity(session: Session, worker_id: str) -> AceStepWorker | None:
    return session.get(AceStepWorker, worker_id)


def list_worker_identities(session: Session) -> list[AceStepWorker]:
    return session.query(AceStepWorker).order_by(AceStepWorker.id).all()
