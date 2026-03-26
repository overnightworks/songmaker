# Observability

## Problem

Currently text logs only. No way to know queue depth, job duration, error rates, or VRAM usage without grepping log files. No structured logging for parsing by log aggregators. No metrics endpoint for dashboards or alerts.

For a single-user personal project this is acceptable. This plan is for when the system serves multiple users or needs operational visibility.

## Design

### Phase 1: Structured logging

Replace plain text log messages with structured JSON logging using `structlog` or Python's built-in `logging` with a JSON formatter.

```python
log.info("job_completed", job_id=job_id, duration_s=elapsed, job_type="generate")
```

Output:
```json
{"event": "job_completed", "job_id": "abc123", "duration_s": 45.2, "job_type": "generate", "timestamp": "..."}
```

Controlled by env var `LOG_FORMAT=json` (default: plain text for development).

Files: `server.py` (configure formatter), all modules using `log.*` (add structured fields).

### Phase 2: `/metrics` endpoint

Expose key operational metrics at `/metrics` (no auth, rate-limited by IP):

| Metric | Type | Source |
|--------|------|--------|
| `songmaker_jobs_total` | counter | `jobs.py` (by type and status) |
| `songmaker_jobs_active` | gauge | DB query |
| `songmaker_job_duration_seconds` | histogram | `jobs.py` (completed_at - started_at) |
| `songmaker_queue_depth` | gauge | `gpu_queue._queue.qsize()` |
| `songmaker_gpu_vram_mb` | gauge | `torch.cuda.memory_allocated()` |
| `songmaker_http_requests_total` | counter | `AccessLogMiddleware` |
| `songmaker_http_request_duration_seconds` | histogram | `AccessLogMiddleware` |

Implementation options:
- **Lightweight**: Custom `/metrics` endpoint returning JSON (no dependencies)
- **Prometheus**: `prometheus-fastapi-instrumentator` + custom metrics via `prometheus_client`

For this project, the lightweight JSON approach is sufficient. Add Prometheus later if needed.

### Phase 3: Health endpoint

`/health` endpoint (no auth) returning:

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

Useful for container orchestration liveness/readiness probes.

## Files to change

| Phase | Files | Effort |
|-------|-------|--------|
| 1 | `server.py`, new `logging_config.py` | Small |
| 2 | `server.py` (new endpoint), `gpu_queue.py`, `jobs.py` | Medium |
| 3 | `server.py` (new endpoint), `gpu_queue.py` | Small |

## Scope

Medium overall. Each phase is independently shippable. Phase 1 is the highest ROI.
