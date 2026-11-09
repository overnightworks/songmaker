"""Health and metrics endpoints."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text

from songmaker_cli import acestep_state, arq_pool, redis_client, settings
from songmaker_cli.agent.mcp import Exclusion, exclude_route
from songmaker_cli.api_models.health import HealthResponse, HealthSignals, HealthStatusResponse
from songmaker_cli.api_models.release import ReleaseInfo
from songmaker_cli.app_context import AppContext
from songmaker_cli.db.queries.auth import count_active_sessions
from songmaker_cli.db.queries.jobs import (
    count_total_queued_jobs,
    job_counts_by_type_and_status,
    job_duration_stats,
    last_job_failure_time,
)
from songmaker_cli.db.queries.workers import list_worker_identities

PROM_HTTP_REQUESTS_TOTAL: Final[str] = "songmaker_http_requests_total"
PROM_HTTP_REQUEST_DURATION_MS: Final[str] = "songmaker_http_request_duration_milliseconds_total"
PROM_ACTIVE_SESSIONS: Final[str] = "songmaker_active_sessions"
PROM_JOBS_TOTAL: Final[str] = "songmaker_jobs_total"
# When the newest job failure finished, as Unix time. A timestamp rather
# than a failure counter, because every counter-shaped answer needs history
# the alarm may not have: a per-type songmaker_jobs_total{status="failed"}
# series only comes into existence WITH the first failure of that type, and
# even an always-exported total reads 1 on Prometheus' FIRST sample if the
# failure happened between the web container becoming healthy and that
# first scrape. increase() finds no rise across a series' first sample
# either way, so exactly the first failure of a fresh stack went unalerted.
# "How long ago was the last one" needs no history: one sample carries the
# whole answer.
PROM_LAST_JOB_FAILURE_TIMESTAMP: Final[str] = "songmaker_last_job_failure_timestamp_seconds"
# What that metric reads while nothing has ever failed: the Unix epoch,
# which puts `time() - <metric>` decades outside every alert window
# without the series ever having to be absent.
PROM_NEVER_FAILED_TIMESTAMP: Final[float] = 0.0
PROM_JOB_DURATION_SECONDS: Final[str] = "songmaker_job_duration_seconds"
# Labeled by queue ("music"/"scoring"), the arq queue names the workers
# actually run on. Renders as songmaker_queue_depth{queue="music"} etc.
# A single unlabeled value would read the arq client library's own default
# queue key, which nothing in this codebase ever enqueues to, so it would
# always be 0.
PROM_QUEUE_DEPTH: Final[str] = "songmaker_queue_depth"
PROM_ACESTEP_WORKERS_TOTAL: Final[str] = "songmaker_acestep_workers_total"
PROM_ACESTEP_WORKER_LOADED_MODELS: Final[str] = "songmaker_acestep_worker_loaded_models"
PROM_ACESTEP_WORKER_QUEUE_DEPTH: Final[str] = "songmaker_acestep_worker_queue_depth"
# Per-worker VRAM from the acestep-worker's own heartbeat. The songmaker-web
# container has no GPU runtime and no NVML, so it cannot produce a
# host-level GPU figure itself.
PROM_ACESTEP_WORKER_VRAM_USED_GB: Final[str] = "songmaker_acestep_worker_vram_used_gigabytes"
PROM_ACESTEP_WORKER_VRAM_TOTAL_GB: Final[str] = "songmaker_acestep_worker_vram_total_gigabytes"
PROM_CONTENT_TYPE: Final[str] = "text/plain; version=0.0.4; charset=utf-8"
PROM_BACKGROUND_LOOP_CONSECUTIVE_FAILURES: Final[str] = (
    "songmaker_background_loop_consecutive_failures"
)
PROM_BACKGROUND_LOOP_ALIVE: Final[str] = "songmaker_background_loop_alive"

router = APIRouter()


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


class _InlineScriptCollector(HTMLParser):
    """Collect the text of every script element that loads no ``src``."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []
        self._open_script: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and all(name != "src" for name, _ in attrs):
            self._open_script = []

    def handle_data(self, data: str) -> None:
        if self._open_script is not None:
            self._open_script.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._open_script is not None:
            self.scripts.append("".join(self._open_script))
            self._open_script = None


def _csp_sha256(script: str) -> str:
    digest = hashlib.sha256(script.encode()).digest()
    return f"sha256-{base64.b64encode(digest).decode()}"


def compute_script_hashes(index_html: Path) -> list[str]:
    if not index_html.exists():
        return []
    collector = _InlineScriptCollector()
    collector.feed(index_html.read_text())
    collector.close()
    return [_csp_sha256(script) for script in collector.scripts]


def _check_db(ctx: AppContext) -> bool:
    try:
        with ctx.db() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _gauge(name: str, help_text: str, value: int | float) -> list[str]:
    return [f"# HELP {name} {help_text}", f"# TYPE {name} gauge", f"{name} {value}"]


def _counter(name: str, help_text: str, value: int | float) -> list[str]:
    return [f"# HELP {name} {help_text}", f"# TYPE {name} counter", f"{name} {value}"]


def _labelled_gauge(
    name: str, help_text: str, samples: Iterable[tuple[str, int | float]],
) -> list[str]:
    return [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} gauge",
        *(f"{name}{{{labels}}} {value}" for labels, value in samples),
    ]


def _format_prometheus(metrics: _PrometheusMetrics) -> str:
    lines: list[str] = []

    lines.append(f"# HELP {PROM_HTTP_REQUESTS_TOTAL} Total HTTP requests by method and status.")
    lines.append(f"# TYPE {PROM_HTTP_REQUESTS_TOTAL} counter")
    for field, count in metrics.http_snapshot["http_requests_total"].items():
        method, status = field.split(" ", 1)
        lines.append(
            f'{PROM_HTTP_REQUESTS_TOTAL}{{method="{method}",status="{status}"}} {count}'
        )

    lines.extend(_counter(
        PROM_HTTP_REQUEST_DURATION_MS,
        "Cumulative HTTP request duration in milliseconds.",
        metrics.http_snapshot["http_request_duration_total_ms"],
    ))

    lines.extend(_gauge(
        PROM_ACTIVE_SESSIONS, "Number of active user sessions.", metrics.active_sessions,
    ))
    lines.extend(_labelled_gauge(
        PROM_JOBS_TOTAL, "Total jobs by type and status.",
        (
            (f'type="{job_type}",status="{status}"', count)
            for job_type, statuses in sorted(metrics.jobs_by_type.items())
            for status, count in sorted(statuses.items())
        ),
    ))
    lines.extend(_gauge(
        PROM_LAST_JOB_FAILURE_TIMESTAMP,
        "Unix time of the newest job failure, 0 while nothing has ever failed.",
        metrics.last_job_failure_epoch_seconds,
    ))
    lines.extend(_labelled_gauge(
        PROM_JOB_DURATION_SECONDS, "Job duration statistics for completed jobs.",
        (
            (f'quantile="{label}"', value)
            for label, value in (
                ("avg", metrics.duration_avg),
                ("min", metrics.duration_min),
                ("max", metrics.duration_max),
            )
            if value is not None
        ),
    ))
    lines.extend(_labelled_gauge(
        PROM_QUEUE_DEPTH, "Number of jobs waiting per arq queue.",
        ((f'queue="{queue}"', depth) for queue, depth in (
            ("music", metrics.music_queue_depth), ("scoring", metrics.scoring_queue_depth),
        )),
    ))
    lines.extend(_labelled_gauge(
        PROM_ACESTEP_WORKERS_TOTAL, "Total registered acestep workers by status.",
        ((f'status="{status}"', count) for status, count in (
            ("online", metrics.acestep_workers_online),
            ("loading", metrics.acestep_workers_loading),
            ("offline", metrics.acestep_workers_offline),
        )),
    ))
    lines.extend(_labelled_gauge(
        PROM_ACESTEP_WORKER_LOADED_MODELS, "Number of loaded models per worker.",
        (
            (f'worker_id="{worker_id}"', count)
            for worker_id, count in sorted(metrics.acestep_worker_loaded_counts.items())
        ),
    ))
    lines.extend(_labelled_gauge(
        PROM_ACESTEP_WORKER_QUEUE_DEPTH, "Per-worker generation queue depth.",
        (
            (f'worker_id="{worker_id}"', depth)
            for worker_id, depth in sorted(metrics.acestep_worker_queue_depths.items())
        ),
    ))
    lines.extend(_labelled_gauge(
        PROM_ACESTEP_WORKER_VRAM_USED_GB, "Per-worker VRAM used, from its own heartbeat.",
        (
            (f'worker_id="{worker_id}"', used_gb)
            for worker_id, used_gb in sorted(metrics.acestep_worker_vram_used_gb.items())
        ),
    ))
    lines.extend(_labelled_gauge(
        PROM_ACESTEP_WORKER_VRAM_TOTAL_GB, "Per-worker VRAM budget, from its heartbeat.",
        (
            (f'worker_id="{worker_id}"', total_gb)
            for worker_id, total_gb in sorted(metrics.acestep_worker_vram_total_gb.items())
        ),
    ))
    lines.extend(_labelled_gauge(
        PROM_BACKGROUND_LOOP_CONSECUTIVE_FAILURES, "Consecutive failures per background loop.",
        (
            (f'loop="{name}"', failures)
            for name, failures in sorted(metrics.background_loop_consecutive_failures.items())
        ),
    ))
    lines.extend(_labelled_gauge(
        PROM_BACKGROUND_LOOP_ALIVE, "Whether each background loop task is alive.",
        (
            (f'loop="{name}"', int(alive))
            for name, alive in sorted(metrics.background_loop_alive.items())
        ),
    ))

    lines.append("")
    return "\n".join(lines)


_bearer_credentials = HTTPBearer(auto_error=False)


def require_monitoring_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_credentials),
    ],
) -> None:
    """Admit only Prometheus's own token; one uniform 401 tells a prober nothing."""
    configured = settings.get_settings().songmaker_monitoring_token
    # Prometheus trims its credentials file, so the configured value is trimmed alike.
    expected = configured.get_secret_value().strip() if configured else ""
    if not expected:
        raise HTTPException(503, "Monitoring not configured")
    presented = credentials.credentials if credentials else ""
    if not hmac.compare_digest(presented.encode(), expected.encode()):
        raise HTTPException(
            401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"},
        )


@router.get(
    "/metrics",
    dependencies=[Depends(require_monitoring_token)],
    openapi_extra=exclude_route(Exclusion.NOT_A_PERSONS_ACTION),
)
async def metrics_endpoint(request: Request) -> PlainTextResponse:
    http_metrics = request.app.state.http_metrics

    ctx: AppContext = request.app.state.ctx
    with ctx.db() as session:
        jobs_by_type = job_counts_by_type_and_status(session)
        duration = job_duration_stats(session)
        last_job_failure = last_job_failure_time(session)
        active_sessions = count_active_sessions(session)
        acestep_workers = list_worker_identities(session)

    music_queue_depth = await arq_pool.get_music_queue_depth()
    scoring_queue_depth = await arq_pool.get_scoring_queue_depth()

    pool = arq_pool.get_arq_pool()
    background_loop_metrics = request.app.state.background_loop_registry.loop_health()
    workers_online = 0
    workers_loading = 0
    workers_offline = 0
    loaded_counts: dict[str, int] = {}
    queue_depths: dict[str, int] = {}
    vram_used_gb: dict[str, float] = {}
    vram_total_gb: dict[str, float] = {}
    for w in acestep_workers:
        state = await acestep_state.read_worker_state(pool, w.id)
        if not acestep_state.worker_is_online(state):
            workers_offline += 1
            loaded_counts[w.id] = 0
            queue_depths[w.id] = 0
            continue
        if state.get("target_loading"):
            workers_loading += 1
        else:
            workers_online += 1
        loaded_counts[w.id] = len(state.get("loaded", []))
        queue_depths[w.id] = await acestep_state.read_queue_depth(pool, w.id)
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


async def _read_health_signals(request: Request) -> HealthSignals:
    ctx: AppContext = request.app.state.ctx
    startup_time: datetime = getattr(
        request.app.state, "startup_time", datetime.now(timezone.utc),
    )
    uptime = int((datetime.now(timezone.utc) - startup_time).total_seconds())

    db_ok = _check_db(ctx)

    music_running = await arq_pool.is_music_worker_healthy()
    scoring_running = await arq_pool.is_scoring_worker_healthy()
    music_queue_depth = await arq_pool.get_music_queue_depth()
    scoring_queue_depth = await arq_pool.get_scoring_queue_depth()

    pool = arq_pool.get_arq_pool()
    config = settings.get_settings()
    with ctx.db() as session:
        acestep_workers = list_worker_identities(session)
        active_jobs_count = count_total_queued_jobs(session)
    queue_depth_cap_reached = active_jobs_count >= config.max_queue_depth
    workers_total = len(acestep_workers)
    workers_online = 0
    workers_lm_failed = False
    for w in acestep_workers:
        state = await acestep_state.read_worker_state(pool, w.id)
        if acestep_state.worker_is_online(state):
            workers_online += 1
        workers_lm_failed |= await acestep_state.worker_lm_failed(pool, w.id)

    redis_ok = redis_client.redis_health(ctx.redis)
    return HealthSignals(
        db_ok=db_ok,
        redis_ok=redis_ok,
        music_running=music_running,
        scoring_running=scoring_running,
        music_queue_depth=music_queue_depth,
        scoring_queue_depth=scoring_queue_depth,
        workers_total=workers_total,
        workers_online=workers_online,
        workers_lm_failed=workers_lm_failed,
        queue_depth_cap_reached=queue_depth_cap_reached,
        uptime_seconds=uptime,
        background_loops=request.app.state.background_loop_registry.loop_health(),
        release=ReleaseInfo.from_settings(config),
    )


@router.get("/health", openapi_extra=exclude_route(Exclusion.NOT_A_PERSONS_ACTION))
async def health_check(request: Request) -> HealthStatusResponse:
    return HealthStatusResponse.from_signals(await _read_health_signals(request))


@router.get(
    "/health/details",
    dependencies=[Depends(require_monitoring_token)],
    openapi_extra=exclude_route(Exclusion.NOT_A_PERSONS_ACTION),
)
async def health_details(request: Request) -> HealthResponse:
    return HealthResponse.from_signals(await _read_health_signals(request))
