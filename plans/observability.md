# Observability

## Problem

All logging is free-text `log.info("ACCESS %s %s %s %d (%.0fms)", ...)`. No structured fields, no metrics, no health endpoint. With multiple users, you need to answer "which user's job failed?", "how deep is the queue?", "is ACE-Step healthy?" — and grep won't cut it.

## Phases

### Phase 1: Structured Logging (structlog)

Drop-in `structlog` with JSON output in production, human-readable in dev. Zero changes to existing `log.info(...)` call sites — structlog wraps stdlib logging transparently.

**Why structlog over stdlib JSON formatter:**
- Processors pipeline (add user_id, request_id, job_id automatically)
- Context binding via contextvars (persists across calls within a request/job)
- Dev mode: colored human-readable output. Prod mode: JSON lines.

**Implementation:**

1. Add `structlog>=24.0` to `pyproject.toml`
2. New file `songmaker_cli/logging_config.py` (~40 lines):

```python
import logging
import os
import structlog

def configure_logging() -> None:
    json_mode = os.environ.get("LOG_FORMAT", "text") == "json"

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_mode:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[*shared_processors, renderer],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
```

3. Bind context in middleware:

```python
# AccessLogMiddleware — clear and bind per-request context
structlog.contextvars.clear_contextvars()
structlog.contextvars.bind_contextvars(ip=ip, method=request.method, path=request.url.path)

# get_current_user — after auth resolves
structlog.contextvars.bind_contextvars(user_id=user.id)
```

4. Bind context in job runners:

```python
# jobs.py run_generation_job / run_scoring_job
structlog.contextvars.bind_contextvars(job_id=job_id, job_type="generate", song_id=song_id)
```

5. Call `configure_logging()` in `server.py:run_server()` before `create_app()`.

**Output examples:**

Dev (`LOG_FORMAT=text`, default):
```
2026-03-26 14:32:01 [info] ACCESS POST /api/songs/abc/generate 200 (45ms)  user_id=usr_123
```

Prod (`LOG_FORMAT=json`):
```json
{"event": "ACCESS", "ip": "192.168.1.5", "method": "POST", "path": "/api/songs/abc/generate", "status": 200, "duration_ms": 45, "user_id": "usr_123", "level": "info", "timestamp": "2026-03-26T14:32:01Z"}
```

**Files to change:**
- New: `songmaker_cli/logging_config.py` (~40 lines)
- `server.py` — call `configure_logging()`, update AccessLogMiddleware to bind contextvars
- `middleware.py` — bind `user_id` after auth
- `jobs.py` — bind `job_id`, `job_type` at job start
- `pyproject.toml` — add `structlog` dependency

**Files NOT changed:** every module calling `log.info(...)` — stdlib integration handles them.

**Convention:** stick with `logging.getLogger(__name__)`, not `structlog.get_logger()`.

### Phase 2: Metrics Endpoint

Expose `/metrics` (no auth, IP rate-limited) with operational data:

| Metric | Type | Source |
|--------|------|--------|
| `jobs_total` | counter | DB query (by type and status) |
| `jobs_active` | gauge | DB query |
| `job_duration_seconds` | summary | `completed_at - started_at` |
| `queue_depth` | gauge | `gpu_queue._queue.qsize()` |
| `gpu_vram_mb` | gauge | `torch.cuda.memory_allocated()` |
| `http_requests_total` | counter | AccessLogMiddleware |
| `http_request_duration_seconds` | summary | AccessLogMiddleware |

Lightweight JSON endpoint — no Prometheus dependency. Add Prometheus later if needed.

**Files to change:**
- `server.py` — new `/metrics` endpoint
- `gpu_queue.py` — expose `queue_depth` property
- Possibly: in-memory counters in middleware for request counts/durations

### Phase 3: Health Endpoint

`/health` (no auth) for liveness/readiness probes:

```json
{
  "status": "ok",
  "gpu_queue": "running",
  "queue_depth": 2,
  "db": "ok",
  "acestep": "running",
  "uptime_seconds": 3600
}
```

**Files to change:**
- `server.py` — new `/health` endpoint
- `gpu_queue.py` — expose `is_running` and ACE-Step status

## Effort

| Phase | Effort | Independently shippable? |
|-------|--------|--------------------------|
| 1 — Structured logging | Small (~2 hours) | Yes |
| 2 — Metrics endpoint | Medium (~3 hours) | Yes |
| 3 — Health endpoint | Small (~1 hour) | Yes |

Phase 1 is the highest ROI. Phases 2+3 matter for deployment and multi-user monitoring.

## Test Changes

- Phase 1: none required (structlog wraps stdlib transparently). Optional: verify JSON output keys.
- Phase 2: test `/metrics` returns expected JSON shape.
- Phase 3: test `/health` returns expected fields and status codes.

## Risks

- structlog adds ~1ms overhead per log call (negligible).
- Metrics endpoint with DB queries on every hit — cache results for 5-10s to avoid load.
