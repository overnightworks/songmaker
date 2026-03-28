"""Health and metrics endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from songmaker_cli.app_context import AppContext

router = APIRouter()


def _get_gpu_vram_mb() -> float | None:
    from songmaker_cli.gpu_util import get_gpu_memory_used_mb
    return get_gpu_memory_used_mb()


def _compute_script_hash(index_html: Path) -> str:
    if not index_html.exists():
        return ""
    import hashlib
    import re
    content = index_html.read_text()
    match = re.search(r"<script>(.*?)</script>", content, re.DOTALL)
    if not match:
        return ""
    import base64
    digest = hashlib.sha256(match.group(1).encode()).digest()
    return f"sha256-{base64.b64encode(digest).decode()}"


def _check_db(ctx: AppContext) -> bool:
    try:
        from sqlalchemy import text
        with ctx.db() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@router.get("/metrics")
async def metrics_endpoint(request: Request) -> JSONResponse:
    http_metrics = request.app.state.http_metrics

    from songmaker_cli.db.queries import job_counts_by_type_and_status, job_duration_stats
    ctx: AppContext = request.app.state.ctx
    with ctx.db() as session:
        jobs_by_type = job_counts_by_type_and_status(session)
        duration = job_duration_stats(session)

    gpu_vram_mb = _get_gpu_vram_mb()

    from songmaker_cli.arq_pool import get_queue_depth
    queue_depth = await get_queue_depth()

    return JSONResponse({
        "jobs_total": jobs_by_type,
        "jobs_active": sum(
            counts.get("queued", 0) + counts.get("running", 0)
            for counts in jobs_by_type.values()
        ),
        "job_duration_seconds": duration,
        "queue_depth": queue_depth,
        "gpu_vram_mb": gpu_vram_mb,
        **http_metrics.snapshot(),
    })


@router.get("/health")
async def health_check(request: Request) -> JSONResponse:
    ctx: AppContext = request.app.state.ctx
    startup_time: datetime = getattr(
        request.app.state, "startup_time", datetime.now(timezone.utc),
    )
    uptime = int((datetime.now(timezone.utc) - startup_time).total_seconds())

    db_ok = _check_db(ctx)

    from songmaker_cli.arq_pool import get_active_model, get_queue_depth, is_worker_healthy
    worker_running = await is_worker_healthy()
    queue_depth = await get_queue_depth()
    acestep_model = await get_active_model()

    if acestep_model is not None:
        acestep = "healthy"
    else:
        from songmaker_cli.acestep_manager import AceStepManager
        mgr = AceStepManager()
        acestep = "healthy" if mgr.is_healthy() else "unknown"

    from songmaker_cli.redis_client import redis_health
    redis_ok = redis_health(ctx.redis)

    session_cache = getattr(request.app.state, "session_cache", None)
    session_cache_failures = (
        session_cache.consecutive_failures if session_cache else 0
    )

    degraded = not db_ok or not worker_running or not redis_ok
    return JSONResponse({
        "status": "degraded" if degraded else "ok",
        "worker": "running" if worker_running else "stopped",
        "queue_depth": queue_depth,
        "db": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "redis_session_cache_failures": session_cache_failures,
        "acestep": acestep,
        "acestep_model": acestep_model,
        "uptime_seconds": uptime,
    })
