"""Health and metrics endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import (
    PROM_ACTIVE_SESSIONS,
    PROM_CONTENT_TYPE,
    PROM_GPU_VRAM_MB,
    PROM_HTTP_REQUEST_DURATION_MS,
    PROM_HTTP_REQUESTS_TOTAL,
    PROM_JOB_DURATION_SECONDS,
    PROM_JOBS_TOTAL,
    PROM_QUEUE_DEPTH,
)

router = APIRouter()


def _get_gpu_vram_mb() -> float | None:
    from songmaker_cli.gpu_util import get_gpu_memory_used_mb
    return get_gpu_memory_used_mb()


def _compute_script_hashes(index_html: Path) -> list[str]:
    if not index_html.exists():
        return []
    import base64
    import hashlib
    import re
    content = index_html.read_text()
    hashes = []
    for match in re.finditer(r"<script>(.*?)</script>", content, re.DOTALL):
        digest = hashlib.sha256(match.group(1).encode()).digest()
        hashes.append(f"sha256-{base64.b64encode(digest).decode()}")
    return hashes


def _check_db(ctx: AppContext) -> bool:
    try:
        from sqlalchemy import text
        with ctx.db() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _format_prometheus(
    http_snapshot: dict,
    jobs_by_type: dict[str, dict[str, int]],
    duration_avg: float | None,
    duration_min: float | None,
    duration_max: float | None,
    queue_depth: int,
    gpu_vram_mb: float | None,
    active_sessions: int,
) -> str:
    lines: list[str] = []

    lines.append(f"# HELP {PROM_HTTP_REQUESTS_TOTAL} Total HTTP requests by method and status.")
    lines.append(f"# TYPE {PROM_HTTP_REQUESTS_TOTAL} counter")
    for field, count in http_snapshot["http_requests_total"].items():
        method, status = field.split(" ", 1)
        lines.append(
            f'{PROM_HTTP_REQUESTS_TOTAL}{{method="{method}",status="{status}"}} {count}'
        )

    duration_help = "Cumulative HTTP request duration in milliseconds."
    lines.append(f"# HELP {PROM_HTTP_REQUEST_DURATION_MS} {duration_help}")
    lines.append(f"# TYPE {PROM_HTTP_REQUEST_DURATION_MS} counter")
    duration_total = http_snapshot["http_request_duration_total_ms"]
    lines.append(f"{PROM_HTTP_REQUEST_DURATION_MS} {duration_total}")

    lines.append(f"# HELP {PROM_ACTIVE_SESSIONS} Number of active user sessions.")
    lines.append(f"# TYPE {PROM_ACTIVE_SESSIONS} gauge")
    lines.append(f"{PROM_ACTIVE_SESSIONS} {active_sessions}")

    lines.append(f"# HELP {PROM_JOBS_TOTAL} Total jobs by type and status.")
    lines.append(f"# TYPE {PROM_JOBS_TOTAL} gauge")
    for job_type, statuses in sorted(jobs_by_type.items()):
        for status, count in sorted(statuses.items()):
            lines.append(
                f'{PROM_JOBS_TOTAL}{{type="{job_type}",status="{status}"}} {count}'
            )

    lines.append(f"# HELP {PROM_JOB_DURATION_SECONDS} Job duration statistics for completed jobs.")
    lines.append(f"# TYPE {PROM_JOB_DURATION_SECONDS} gauge")
    duration_values = [
        ("avg", duration_avg), ("min", duration_min), ("max", duration_max),
    ]
    for quantile_label, value in duration_values:
        if value is not None:
            lines.append(
                f'{PROM_JOB_DURATION_SECONDS}{{quantile="{quantile_label}"}} {value}'
            )

    lines.append(f"# HELP {PROM_QUEUE_DEPTH} Number of jobs in the queue.")
    lines.append(f"# TYPE {PROM_QUEUE_DEPTH} gauge")
    lines.append(f"{PROM_QUEUE_DEPTH} {queue_depth}")

    if gpu_vram_mb is not None:
        lines.append(f"# HELP {PROM_GPU_VRAM_MB} GPU VRAM usage in megabytes.")
        lines.append(f"# TYPE {PROM_GPU_VRAM_MB} gauge")
        lines.append(f"{PROM_GPU_VRAM_MB} {gpu_vram_mb}")

    lines.append("")
    return "\n".join(lines)


@router.get("/metrics")
async def metrics_endpoint(request: Request) -> PlainTextResponse:
    http_metrics = request.app.state.http_metrics

    from songmaker_cli.db.queries import (
        count_active_sessions,
        job_counts_by_type_and_status,
        job_duration_stats,
    )
    ctx: AppContext = request.app.state.ctx
    with ctx.db() as session:
        jobs_by_type = job_counts_by_type_and_status(session)
        duration = job_duration_stats(session)
        active_sessions = count_active_sessions(session)

    gpu_vram_mb = _get_gpu_vram_mb()

    from songmaker_cli.arq_pool import get_queue_depth
    queue_depth = await get_queue_depth()

    body = _format_prometheus(
        http_snapshot=http_metrics.snapshot(),
        jobs_by_type=jobs_by_type,
        duration_avg=duration.avg,
        duration_min=duration.min,
        duration_max=duration.max,
        queue_depth=queue_depth,
        gpu_vram_mb=gpu_vram_mb,
        active_sessions=active_sessions,
    )
    return PlainTextResponse(body, media_type=PROM_CONTENT_TYPE)


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
