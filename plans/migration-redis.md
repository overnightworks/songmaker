# Migration: In-Memory State → Redis

> **Status: NOT STARTED** — prerequisite for multi-process and multi-user scaling.
> **Depends on: Phase 0 (feature flag infrastructure)**

## Problem

All runtime state lives in process memory. Rate limits, metrics, and GPU queue items are lost on restart and cannot be shared across processes. This blocks `UVICORN_WORKERS > 1` and any form of horizontal scaling.

## Goal

Replace in-memory state with Redis so the server can run multiple worker processes on a single machine (Docker Compose), and later across machines.

## Complete In-Memory State Inventory

Every item below MUST be migrated or explicitly kept local. File:line references are exact.

### Must migrate to Redis

| State | Location | Type | Purpose |
|-------|----------|------|---------|
| IP rate limiter (global) | `middleware.py:119` `_requests: dict[str, deque[float]]` | Sliding window per IP | HTTP request rate limiting |
| IP rate limiter lock | `middleware.py:120` `_lock: threading.Lock()` | Mutex | Thread safety (Redis replaces) |
| Shared album rate limiter | `server.py:594` `shared_limiter = IpRateLimiter(...)` | Same as above | Rate limiting `/shared/` endpoints |
| HTTP metrics counts | `server.py:136` `_request_counts: dict[tuple[str, int], int]` | Counter per method+status | `/metrics` endpoint |
| HTTP metrics totals | `server.py:137-138` `_total_duration_ms`, `_total_requests` | Float, int | Aggregate stats |
| HTTP metrics lock | `server.py:135` `_lock: threading.Lock()` | Mutex | Thread safety (Redis replaces) |
| Metrics endpoint cache | `server.py:487-489` `_metrics_cache`, `_metrics_cache_time`, `_metrics_lock` | Dict + float + Lock | 5s TTL cache for /metrics |
| GPU job queue | `gpu_queue.py:57` `_queue: Queue[GpuJob \| None]` | stdlib Queue | Job submission → worker |

### Must stay in-memory (per-host state)

| State | Location | Why it stays |
|-------|----------|-------------|
| ACE-Step process handle | `gpu_queue.py:63` `_acestep_process` | Local subprocess, per-host |
| GPU mode tracking | `gpu_queue.py:61` `_current_mode` | Per-host GPU state |
| Cached model name | `gpu_queue.py:64` `_cached_model` | Per-host model cache |
| Worker thread handle | `gpu_queue.py:58` `_worker` | Thread lifecycle, per-host |
| Cleanup thread handle | `gpu_queue.py:59` `_cleanup_thread` | Thread lifecycle, per-host |
| Shutdown event | `gpu_queue.py:60` `_shutdown_event` | Thread coordination, per-host |
| Running flag | `gpu_queue.py:62` `_running` | Thread lifecycle, per-host |

## Steps

### Phase 1: Add Redis dependency

- [ ] Add `redis[hiredis]>=5.0` to `pyproject.toml` server extras
- [ ] Create `src/songmaker_cli/redis_client.py`:
  - `create_redis(url: str) -> Redis` — connection pool from URL
  - `redis_health(r: Redis) -> bool` — `r.ping()` with try/except
- [ ] Add `REDIS_URL` env var support (Phase 0 wires this into `server.py`)
- [ ] Pass `Redis | None` instance via `AppContext.redis` (Phase 0 adds this field)
- [ ] Health endpoint (`server.py:533`) reports Redis status when configured
- [ ] Add `fakeredis>=2.0` to dev dependencies for testing

### Phase 2: Rate limiter migration

Create `RedisRateLimiter` class implementing the same interface as `IpRateLimiter` (`middleware.py:110-146`):

- [ ] New class `RedisRateLimiter` in `redis_client.py`:
  - `__init__(self, redis: Redis, prefix: str, max_requests: int, window_seconds: int)`
  - `is_allowed(self, ip: str) -> bool` — sorted set sliding window:
    ```
    now = time.time()
    key = f"{prefix}:{ip}"
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, now - window)  # prune old
    pipe.zadd(key, {str(now): now})               # add current
    pipe.zcard(key)                                # count
    pipe.expire(key, window)                       # TTL = window
    results = pipe.execute()
    return results[2] <= max_requests
    ```
  - No `_evict()` needed — Redis TTL handles cleanup automatically

- [ ] Replace `IpRateLimiter` instantiation in `IpRateLimitMiddleware` (`server.py:300-301`):
  - If `app.state.ctx.redis`: use `RedisRateLimiter(redis, "rl:ip", IP_RATE_LIMIT, IP_RATE_WINDOW)`
  - Else: use current `IpRateLimiter(IP_RATE_LIMIT, IP_RATE_WINDOW)`

- [ ] Replace `shared_limiter` instantiation (`server.py:594`):
  - If Redis: `RedisRateLimiter(redis, "rl:shared", SHARED_RATE_LIMIT, SHARED_RATE_WINDOW_SECONDS)`
  - Else: current `IpRateLimiter(...)`

- [ ] **Failure mode**: If Redis is down, `is_allowed()` must raise → middleware returns 503. Do NOT fail-open (allows unlimited traffic). Wrap Redis calls in try/except, re-raise as `HTTPException(503, "Rate limiting unavailable")`.

- [ ] Test: rate limits survive server restart (Redis persists)
- [ ] Test: rate limits apply across 2 uvicorn workers (same Redis)
- [ ] Test: Redis down → 503 response, not silent allow

### Phase 3: Metrics migration

- [ ] Replace `HttpMetrics` class (`server.py:130-156`) with `RedisHttpMetrics`:
  - `record(method, status, duration_ms)` → `HINCRBY songmaker:metrics:http {method}:{status} 1` + `HINCRBYFLOAT songmaker:metrics:http:duration duration_ms {value}` + `HINCRBY songmaker:metrics:http:total total 1`
  - `snapshot()` → `HGETALL songmaker:metrics:http` + reads from duration/total keys
  - No lock needed — Redis operations are atomic
  - Fallback: keep in-memory `HttpMetrics` when Redis unavailable

- [ ] Replace `_metrics_cache` (`server.py:487-489`):
  - With Redis: cache is unnecessary (Redis reads are fast enough at this scale)
  - Without Redis: keep current 5s TTL cache
  - Remove `_metrics_lock` when using Redis

- [ ] `/metrics` endpoint (`server.py:491-531`): read from Redis or in-memory based on config
- [ ] **Note**: `job_duration_stats()` (`db/queries/jobs.py:141-158`) uses `func.julianday()` which is SQLite-specific. This is a PostgreSQL migration concern, not Redis — but the metrics endpoint calls it, so ensure both migrations coordinate.

### Phase 4: GPU queue durability (only needed for Celery prep)

This phase is optional if Celery migration follows immediately. If there's a gap, implement for durability:

- [ ] Replace `queue.Queue()` (`gpu_queue.py:57`) with Redis list:
  - Submit: `LPUSH songmaker:gpu:queue {json_payload}` (payload: `{"job_id", "job_type", "fn_name", "args", "kwargs"}`)
  - Worker: `BRPOP songmaker:gpu:queue 0` (blocking pop, 0 = wait forever)
  - **Problem**: `fn` is a callable — can't serialize to Redis. Instead, serialize `(job_type, job_id)` and have the worker look up the function by job_type:
    ```python
    _TASK_REGISTRY = {"generate": run_generation_job, "score": run_scoring_job}
    ```
  - Queue depth: `LLEN songmaker:gpu:queue` (replaces `self._queue.qsize()` at `gpu_queue.py:327`)
  - Stale recovery: on startup, `LRANGE songmaker:gpu:queue 0 -1` to inspect orphaned items

- [ ] **Bounded queue**: `if redis.llen("songmaker:gpu:queue") >= MAX_QUEUE_DEPTH: raise HTTPException(429)` in `submit()` — currently the database check in `api_helpers.py:67` guards this, but adding a Redis check is defense-in-depth.

- [ ] If Redis unavailable at startup, fall back to `queue.Queue()` (current behavior)

## Design Decisions

### Rate limiter: sorted set vs token bucket
Sorted set mirrors the current sliding window exactly. Token bucket is simpler in Redis (single key + TTL) but changes the rate limiting behavior. **Decision: sorted set** — keeps behavior identical.

### Redis failure mode
If Redis is down: rate-limited endpoints return 503, NOT silently allow all traffic. The health check reports degraded status. This is fail-closed — safer than fail-open.

### Single Redis instance vs Sentinel/Cluster
Single instance is fine for single-machine Docker Compose. Document that Sentinel adds HA if needed later.

### Two IpRateLimiter instances
The codebase has TWO separate rate limiters using the same class:
1. Global IP rate limiter (`server.py:300-301`, `middleware.py:119`)
2. Shared album rate limiter (`server.py:594`)

Both must be migrated. Use different Redis key prefixes (`rl:ip:` vs `rl:shared:`).

## Testing

- Unit tests: `fakeredis` library for Redis mock
- Integration test: Docker Compose with real Redis, verify rate limits across 2 uvicorn workers
- Chaos test: kill Redis mid-request, verify 503 not 500 or silent allow
- Regression test: all existing tests pass with `REDIS_URL` unset (in-memory fallback)

## Migration Safety

- Feature flag: `REDIS_URL` env var — unset means in-memory fallback (current behavior)
- Deploy with Redis alongside current in-memory for comparison period
- Remove in-memory fallback once stable
