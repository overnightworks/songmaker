"""Health and metrics endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, TypeAdapter

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import (
    PROM_ACESTEP_WORKER_LOADED_MODELS,
    PROM_ACESTEP_WORKER_QUEUE_DEPTH,
    PROM_ACESTEP_WORKER_VRAM_TOTAL_GB,
    PROM_ACESTEP_WORKER_VRAM_USED_GB,
    PROM_ACESTEP_WORKERS_TOTAL,
    PROM_ACTIVE_SESSIONS,
    PROM_BACKGROUND_LOOP_ALIVE,
    PROM_BACKGROUND_LOOP_CONSECUTIVE_FAILURES,
    PROM_CONTENT_TYPE,
    PROM_HTTP_REQUEST_DURATION_MS,
    PROM_HTTP_REQUESTS_TOTAL,
    PROM_JOB_DURATION_SECONDS,
    PROM_JOBS_TOTAL,
    PROM_LAST_JOB_FAILURE_TIMESTAMP,
    PROM_NEVER_FAILED_TIMESTAMP,
    PROM_QUEUE_DEPTH,
)
from songmaker_cli.lifecycle import BackgroundLoopName, BackgroundLoopStatus

router = APIRouter()


class BackgroundLoopResponse(BaseModel):
    state: BackgroundLoopStatus
    consecutive_failures: int
    last_error: str | None


_background_loop_response_adapter = TypeAdapter(
    dict[BackgroundLoopName, BackgroundLoopResponse],
)


@dataclass(frozen=True)
class _PrometheusMetrics:
    http_snapshot: dict
    jobs_by_type: dict[str, dict[str, int]]
    last_job_failure_epoch_seconds: float
    duration_avg: float | None
    duration_min: float | None
    duration_max: float | None
    music_queue_depth: int
    scoring_queue_depth: int
    active_sessions: int
    acestep_workers_online: int
    acestep_workers_loading: int
    acestep_workers_offline: int
    acestep_worker_loaded_counts: dict[str, int]
    acestep_worker_queue_depths: dict[str, int]
    acestep_worker_vram_used_gb: dict[str, float]
    acestep_worker_vram_total_gb: dict[str, float]
    background_loop_consecutive_failures: dict[str, int]
    background_loop_alive: dict[str, bool]


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


def _format_prometheus(metrics: _PrometheusMetrics) -> str:
    http_snapshot = metrics.http_snapshot
    jobs_by_type = metrics.jobs_by_type
    last_job_failure_epoch_seconds = metrics.last_job_failure_epoch_seconds
    duration_avg = metrics.duration_avg
    duration_min = metrics.duration_min
    duration_max = metrics.duration_max
    music_queue_depth = metrics.music_queue_depth
    scoring_queue_depth = metrics.scoring_queue_depth
    active_sessions = metrics.active_sessions
    acestep_workers_online = metrics.acestep_workers_online
    acestep_workers_loading = metrics.acestep_workers_loading
    acestep_workers_offline = metrics.acestep_workers_offline
    acestep_worker_loaded_counts = metrics.acestep_worker_loaded_counts
    acestep_worker_queue_depths = metrics.acestep_worker_queue_depths
    acestep_worker_vram_used_gb = metrics.acestep_worker_vram_used_gb
    acestep_worker_vram_total_gb = metrics.acestep_worker_vram_total_gb
    background_loop_consecutive_failures = metrics.background_loop_consecutive_failures
    background_loop_alive = metrics.background_loop_alive
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

    lines.append(
        f"# HELP {PROM_LAST_JOB_FAILURE_TIMESTAMP} "
        "Unix time of the newest job failure, 0 while nothing has ever failed.",
    )
    lines.append(f"# TYPE {PROM_LAST_JOB_FAILURE_TIMESTAMP} gauge")
    lines.append(f"{PROM_LAST_JOB_FAILURE_TIMESTAMP} {last_job_failure_epoch_seconds}")

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

    lines.append(f"# HELP {PROM_QUEUE_DEPTH} Number of jobs waiting per arq queue.")
    lines.append(f"# TYPE {PROM_QUEUE_DEPTH} gauge")
    lines.append(f'{PROM_QUEUE_DEPTH}{{queue="music"}} {music_queue_depth}')
    lines.append(f'{PROM_QUEUE_DEPTH}{{queue="scoring"}} {scoring_queue_depth}')

    lines.append(
        f"# HELP {PROM_ACESTEP_WORKERS_TOTAL} Total registered acestep workers by status.",
    )
    lines.append(f"# TYPE {PROM_ACESTEP_WORKERS_TOTAL} gauge")
    lines.append(
        f'{PROM_ACESTEP_WORKERS_TOTAL}{{status="online"}} {acestep_workers_online}',
    )
    lines.append(
        f'{PROM_ACESTEP_WORKERS_TOTAL}{{status="loading"}} {acestep_workers_loading}',
    )
    lines.append(
        f'{PROM_ACESTEP_WORKERS_TOTAL}{{status="offline"}} {acestep_workers_offline}',
    )

    lines.append(
        f"# HELP {PROM_ACESTEP_WORKER_LOADED_MODELS} Number of loaded models per worker.",
    )
    lines.append(f"# TYPE {PROM_ACESTEP_WORKER_LOADED_MODELS} gauge")
    for worker_id, count in sorted(acestep_worker_loaded_counts.items()):
        lines.append(
            f'{PROM_ACESTEP_WORKER_LOADED_MODELS}{{worker_id="{worker_id}"}} {count}',
        )

    lines.append(
        f"# HELP {PROM_ACESTEP_WORKER_QUEUE_DEPTH} Per-worker generation queue depth.",
    )
    lines.append(f"# TYPE {PROM_ACESTEP_WORKER_QUEUE_DEPTH} gauge")
    for worker_id, depth in sorted(acestep_worker_queue_depths.items()):
        lines.append(
            f'{PROM_ACESTEP_WORKER_QUEUE_DEPTH}{{worker_id="{worker_id}"}} {depth}',
        )

    lines.append(
        f"# HELP {PROM_ACESTEP_WORKER_VRAM_USED_GB} Per-worker VRAM used, from its own heartbeat.",
    )
    lines.append(f"# TYPE {PROM_ACESTEP_WORKER_VRAM_USED_GB} gauge")
    for worker_id, used_gb in sorted(acestep_worker_vram_used_gb.items()):
        lines.append(
            f'{PROM_ACESTEP_WORKER_VRAM_USED_GB}{{worker_id="{worker_id}"}} {used_gb}',
        )

    lines.append(
        f"# HELP {PROM_ACESTEP_WORKER_VRAM_TOTAL_GB} Per-worker VRAM budget, from its heartbeat.",
    )
    lines.append(f"# TYPE {PROM_ACESTEP_WORKER_VRAM_TOTAL_GB} gauge")
    for worker_id, total_gb in sorted(acestep_worker_vram_total_gb.items()):
        lines.append(
            f'{PROM_ACESTEP_WORKER_VRAM_TOTAL_GB}{{worker_id="{worker_id}"}} {total_gb}',
        )

    lines.append(
        f"# HELP {PROM_BACKGROUND_LOOP_CONSECUTIVE_FAILURES} "
        "Consecutive failures per background loop.",
    )
    lines.append(f"# TYPE {PROM_BACKGROUND_LOOP_CONSECUTIVE_FAILURES} gauge")
    for name, failures in sorted(background_loop_consecutive_failures.items()):
        lines.append(
            f'{PROM_BACKGROUND_LOOP_CONSECUTIVE_FAILURES}{{loop="{name}"}} {failures}',
        )

    lines.append(f"# HELP {PROM_BACKGROUND_LOOP_ALIVE} Whether each background loop task is alive.")
    lines.append(f"# TYPE {PROM_BACKGROUND_LOOP_ALIVE} gauge")
    for name, alive in sorted(background_loop_alive.items()):
        lines.append(f'{PROM_BACKGROUND_LOOP_ALIVE}{{loop="{name}"}} {int(alive)}')

    lines.append("")
    return "\n".join(lines)


@router.get("/metrics")
async def metrics_endpoint(request: Request) -> PlainTextResponse:
    http_metrics = request.app.state.http_metrics

    from songmaker_cli.acestep_state import (
        read_queue_depth,
        read_worker_state,
        worker_is_online,
    )
    from songmaker_cli.arq_pool import (
        get_arq_pool,
        get_music_queue_depth,
        get_scoring_queue_depth,
    )
    from songmaker_cli.db.queries import (
        count_active_sessions,
        job_counts_by_type_and_status,
        job_duration_stats,
        last_job_failure_time,
        list_worker_identities,
    )
    ctx: AppContext = request.app.state.ctx
    with ctx.db() as session:
        jobs_by_type = job_counts_by_type_and_status(session)
        duration = job_duration_stats(session)
        last_job_failure = last_job_failure_time(session)
        active_sessions = count_active_sessions(session)
        acestep_workers = list_worker_identities(session)

    music_queue_depth = await get_music_queue_depth()
    scoring_queue_depth = await get_scoring_queue_depth()

    pool = get_arq_pool()
    background_loop_metrics = request.app.state.background_loop_registry.loop_health()
    workers_online = 0
    workers_loading = 0
    workers_offline = 0
    loaded_counts: dict[str, int] = {}
    queue_depths: dict[str, int] = {}
    vram_used_gb: dict[str, float] = {}
    vram_total_gb: dict[str, float] = {}
    for w in acestep_workers:
        state = await read_worker_state(pool, w.id)
        if not worker_is_online(state):
            workers_offline += 1
            loaded_counts[w.id] = 0
            queue_depths[w.id] = 0
            continue
        if state.get("target_loading"):
            workers_loading += 1
        else:
            workers_online += 1
        loaded_counts[w.id] = len(state.get("loaded", []))
        queue_depths[w.id] = await read_queue_depth(pool, w.id)
        if state.get("vram_used_gb") is not None:
            vram_used_gb[w.id] = state["vram_used_gb"]
        if state.get("vram_total_gb") is not None:
            vram_total_gb[w.id] = state["vram_total_gb"]

    body = _format_prometheus(_PrometheusMetrics(
        http_snapshot=http_metrics.snapshot(),
        jobs_by_type=jobs_by_type,
        last_job_failure_epoch_seconds=(
            last_job_failure.timestamp() if last_job_failure
            else PROM_NEVER_FAILED_TIMESTAMP
        ),
        duration_avg=duration.avg,
        duration_min=duration.min,
        duration_max=duration.max,
        music_queue_depth=music_queue_depth,
        scoring_queue_depth=scoring_queue_depth,
        active_sessions=active_sessions,
        acestep_workers_online=workers_online,
        acestep_workers_loading=workers_loading,
        acestep_workers_offline=workers_offline,
        acestep_worker_loaded_counts=loaded_counts,
        acestep_worker_queue_depths=queue_depths,
        acestep_worker_vram_used_gb=vram_used_gb,
        acestep_worker_vram_total_gb=vram_total_gb,
        background_loop_consecutive_failures={
            name.value: health.consecutive_failures
            for name, health in background_loop_metrics.items()
        },
        background_loop_alive={
            name.value: health.is_alive for name, health in background_loop_metrics.items()
        },
    ))
    return PlainTextResponse(body, media_type=PROM_CONTENT_TYPE)


@router.get("/health")
async def health_check(request: Request) -> JSONResponse:
    ctx: AppContext = request.app.state.ctx
    startup_time: datetime = getattr(
        request.app.state, "startup_time", datetime.now(timezone.utc),
    )
    uptime = int((datetime.now(timezone.utc) - startup_time).total_seconds())

    db_ok = _check_db(ctx)

    from songmaker_cli.acestep_state import read_worker_state, worker_is_online
    from songmaker_cli.arq_pool import (
        get_arq_pool,
        get_music_queue_depth,
        get_scoring_queue_depth,
        is_music_worker_healthy,
        is_scoring_worker_healthy,
    )
    from songmaker_cli.claude.provider import claude_cli_tool_surface_health
    from songmaker_cli.db.queries import count_total_queued_jobs, list_worker_identities
    from songmaker_cli.settings import get_settings

    music_running = await is_music_worker_healthy()
    scoring_running = await is_scoring_worker_healthy()
    music_queue_depth = await get_music_queue_depth()
    scoring_queue_depth = await get_scoring_queue_depth()

    pool = get_arq_pool()
    settings = get_settings()
    with ctx.db() as session:
        acestep_workers = list_worker_identities(session)
        active_jobs_count = count_total_queued_jobs(session)
    queue_depth_cap_reached = active_jobs_count >= settings.max_queue_depth
    workers_total = len(acestep_workers)
    workers_online = 0
    for w in acestep_workers:
        state = await read_worker_state(pool, w.id)
        if worker_is_online(state):
            workers_online += 1

    if workers_online > 0:
        acestep = "healthy"
    elif workers_total == 0:
        acestep = "unknown"
    else:
        acestep = "unhealthy"

    from songmaker_cli.redis_client import redis_health
    redis_ok = redis_health(ctx.redis)
    background_loop_health = request.app.state.background_loop_registry.loop_health()
    background_loops = _background_loop_response_adapter.validate_python({
        name: {
            "state": health.status,
            "consecutive_failures": health.consecutive_failures,
            "last_error": health.last_error,
        }
        for name, health in background_loop_health.items()
    })

    session_cache = getattr(request.app.state, "session_cache", None)
    session_cache_failures = (
        session_cache.consecutive_failures if session_cache else 0
    )

    degraded = (
        not db_ok
        or (not music_running and not scoring_running)
        or not redis_ok
        or acestep == "unhealthy"
    )
    return JSONResponse({
        "status": "degraded" if degraded else "ok",
        "music_worker": "running" if music_running else "stopped",
        "scoring_worker": "running" if scoring_running else "stopped",
        "music_queue_depth": music_queue_depth,
        "scoring_queue_depth": scoring_queue_depth,
        "db": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "redis_session_cache_failures": session_cache_failures,
        "acestep": acestep,
        "acestep_workers_total": workers_total,
        "acestep_workers_online": workers_online,
        "queue_depth_cap_reached": queue_depth_cap_reached,
        "uptime_seconds": uptime,
        # "ok" / "drift" / "unverified" (#351): whether the mounted Claude
        # CLI's tool surface still matches the co-writer's allowlist. A
        # drifted binary never takes the whole server down — the co-writer
        # path refuses it on its own — but the operator and monitoring
        # should see the state without reading the boot log. This is the
        # gate's *live* answer (round 7), not a value frozen at boot: it
        # reads provider.claude_cli_tool_surface_health(), which every
        # verify_cli_tool_surface() call updates, cache hit or fresh probe
        # alike — a later successful co-writer turn clears an earlier
        # "unverified", and a later drifted build replaces an earlier
        # "ok". Defaults to "unverified" (never a silent "ok") for the
        # narrow window before the boot-time check has run at all.
        "claude_cli_tool_surface": claude_cli_tool_surface_health(),
        "background_loops": _background_loop_response_adapter.dump_python(
            background_loops, mode="json",
        ),
    })
