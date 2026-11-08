"""Application lifecycle helpers -- admin auto-setup and session cleanup."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final

from arq.connections import ArqRedis
from fastapi import FastAPI
from sqlalchemy.orm import Session

from songmaker_cli.acestep_state import decode_redis_text
from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import (
    BACKGROUND_LOOP_FAILURE_THRESHOLD,
    JOB_REAPER_INTERVAL_SECONDS,
    REDIS_KEY_PREFIX,
    RESOURCE_EVENT_CLEANUP_INTERVAL_SECONDS,
    RESOURCE_EVENT_RETENTION_DAYS,
    JobType,
)
from songmaker_cli.health_types import (
    BackgroundLoopName,
    BackgroundLoopRegistry,
)
from songmaker_cli.worker_liveness import WorkerLiveness
from songmaker_cli.worker_liveness import read_worker_liveness as read_liveness_signals

log = logging.getLogger(__name__)

QUEUE_STREAM_CLEANUP_INTERVAL_SECONDS: Final = 4 * 60 * 60
_QUEUE_STREAM_CLEANUP_EVERY_N_TICKS: Final = max(
    1, QUEUE_STREAM_CLEANUP_INTERVAL_SECONDS // RESOURCE_EVENT_CLEANUP_INTERVAL_SECONDS
)
# The web process owns stale-job recovery for every job type.
JOB_REAPER_LOCK_KEY: Final = f"{REDIS_KEY_PREFIX}:job_reaper_lock"
JOB_REAPER_LOCK_TTL_SECONDS: Final = 60


def background_loop_registry(app: FastAPI) -> BackgroundLoopRegistry:
    return app.state.background_loop_registry


def cleanup_expired_resource_events(ctx: AppContext) -> int:
    """Delete delivered event history beyond retention, preserving cursors."""
    from songmaker_cli.db.queries.resource_events import delete_resource_events_before

    cutoff = datetime.now(timezone.utc) - timedelta(days=RESOURCE_EVENT_RETENTION_DAYS)
    with ctx.db() as session:
        deleted = delete_resource_events_before(session, cutoff)
        session.commit()
    if deleted:
        log.info("Resource event cleanup: deleted %d expired event(s)", deleted)
    return deleted


async def resource_event_cleanup_loop(app: FastAPI) -> None:
    """Run periodic background maintenance for the server lifetime.

    Sweeps expired resource-event history every tick and the queue-stream
    snapshot cache every ``_QUEUE_STREAM_CLEANUP_EVERY_N_TICKS`` ticks. The
    queue-stream sweep used to run inline on every snapshot request, holding
    that request's DB session for the duration; it now runs here instead so
    request latency is decoupled from cache-directory size.
    """
    from songmaker_cli.queue_streams import cleanup_expired_queue_streams

    ctx: AppContext = app.state.ctx
    registry = background_loop_registry(app)
    tick = 0
    while True:
        await asyncio.sleep(RESOURCE_EVENT_CLEANUP_INTERVAL_SECONDS)
        tick += 1
        error: Exception | None = None
        try:
            await asyncio.to_thread(cleanup_expired_resource_events, ctx)
        except Exception as exc:
            error = exc
            log.exception("Resource event cleanup failed")
        if tick % _QUEUE_STREAM_CLEANUP_EVERY_N_TICKS == 0:
            try:
                await asyncio.to_thread(cleanup_expired_queue_streams, ctx)
            except Exception as exc:
                if error is None:
                    error = exc
                log.exception("Queue stream cleanup failed")
        if error is None:
            registry.record_success(BackgroundLoopName.RESOURCE_EVENT_CLEANUP)
        else:
            registry.record_failure(BackgroundLoopName.RESOURCE_EVENT_CLEANUP, error)


def _pick_unscored_generations(session: Session, limit: int) -> list[tuple[str, str]]:
    """Return (generation_id, song_id) for up to ``limit`` scoreless generations.

    Oldest first, so a long-standing backlog (issue #222: generations that
    predate auto-scoring) drains before generations an auto-score attempt
    recently failed to reach.
    """
    from songmaker_cli.db.models import Generation, Score

    rows = (
        session.query(Generation.id, Generation.song_id)
        .outerjoin(Score, Score.generation_id == Generation.id)
        .filter(Score.id.is_(None))
        .order_by(Generation.created_at.asc())
        .limit(limit)
        .all()
    )
    return [(gen_id, song_id) for gen_id, song_id in rows]


def _backfill_attempt_key(gen_id: str) -> str:
    from songmaker_cli.constants import SCORE_BACKFILL_ATTEMPTS_KEY_PREFIX

    return f"{SCORE_BACKFILL_ATTEMPTS_KEY_PREFIX}:{gen_id}"


async def _record_backfill_attempt(redis: ArqRedis, gen_id: str) -> None:
    """Bump ``gen_id``'s backfill attempt counter and refresh its TTL.

    Tracking only covers attempts the backfill loop itself makes — the
    real-time auto-score trigger on a fresh generation never touches this.
    """
    from songmaker_cli.constants import (
        SCORE_BACKFILL_ATTEMPT_TTL_SECONDS,
        SCORE_BACKFILL_TRACKED_SET_KEY,
    )

    key = _backfill_attempt_key(gen_id)
    await redis.incr(key)
    await redis.expire(key, SCORE_BACKFILL_ATTEMPT_TTL_SECONDS)
    await redis.sadd(SCORE_BACKFILL_TRACKED_SET_KEY, gen_id)


async def _exhausted_backfill_ids(redis: ArqRedis, gen_ids: list[str]) -> set[str]:
    """Ids that already hit ``SCORE_BACKFILL_MAX_ATTEMPTS``.

    These are skipped until their attempt counter's TTL lapses, so a
    chronically-unscorable generation cannot keep winning the same
    oldest-first batch and starve the rest of the backlog.
    """
    from songmaker_cli.constants import SCORE_BACKFILL_MAX_ATTEMPTS

    if not gen_ids:
        return set()
    counts = await redis.mget([_backfill_attempt_key(gen_id) for gen_id in gen_ids])
    return {
        gen_id
        for gen_id, raw_count in zip(gen_ids, counts, strict=True)
        if (decoded := decode_redis_text(raw_count)) is not None
        and int(decoded) >= SCORE_BACKFILL_MAX_ATTEMPTS
    }


async def _clear_resolved_backfill_attempts(ctx: AppContext, redis: ArqRedis) -> None:
    """Drop attempt-tracking for a tracked generation that now has a score.

    Covers both a backfill dispatch that eventually succeeded and a
    generation scored some other way (e.g. a manual re-score) while it was
    still being tracked here — either way it no longer needs a counter, and
    dropping it now (rather than waiting out the TTL) frees its budget
    immediately if it were ever to regress.
    """
    from songmaker_cli.constants import SCORE_BACKFILL_TRACKED_SET_KEY
    from songmaker_cli.db.models import Score

    tracked_raw = await redis.smembers(SCORE_BACKFILL_TRACKED_SET_KEY)
    if not tracked_raw:
        return
    tracked_ids = [decode_redis_text(gen_id) for gen_id in tracked_raw]

    with ctx.db() as session:
        resolved = {
            gen_id for (gen_id,) in
            session.query(Score.generation_id)
            .filter(Score.generation_id.in_(tracked_ids))
            .distinct()
            .all()
        }

    for gen_id in resolved:
        await redis.delete(_backfill_attempt_key(gen_id))
        await redis.srem(SCORE_BACKFILL_TRACKED_SET_KEY, gen_id)


@dataclass(frozen=True)
class BackfillResult:
    dispatched: int
    first_error: Exception | None


async def backfill_unscored_generations(
    ctx: AppContext,
    redis: ArqRedis,
) -> BackfillResult:
    """Auto-score one throttled batch of generations that still have no score.

    Covers both a generation that predates auto-scoring and one an earlier
    auto-score attempt could not reach (worker down, enqueue failure) — both
    look identical here: no ``Score`` row yet. Each generation is handled
    independently so one bad row cannot stop the rest of the batch, and a
    generation that keeps failing to ever get a score row is skipped after
    ``SCORE_BACKFILL_MAX_ATTEMPTS`` so it cannot starve the rest of the
    backlog out of every batch.
    """
    from songmaker_cli.constants import (
        SCORE_BACKFILL_BATCH_SIZE,
        SCORE_BACKFILL_CANDIDATE_POOL_SIZE,
    )
    from songmaker_cli.jobs import _auto_score_generation

    await _clear_resolved_backfill_attempts(ctx, redis)

    with ctx.db() as session:
        candidates = _pick_unscored_generations(session, SCORE_BACKFILL_CANDIDATE_POOL_SIZE)

    exhausted = await _exhausted_backfill_ids(redis, [gen_id for gen_id, _song_id in candidates])
    eligible = [
        (gen_id, song_id) for gen_id, song_id in candidates if gen_id not in exhausted
    ][:SCORE_BACKFILL_BATCH_SIZE]

    dispatched = 0
    first_error: Exception | None = None
    for gen_id, song_id in eligible:
        try:
            await _record_backfill_attempt(redis, gen_id)
            await _auto_score_generation(redis, ctx.db, gen_id, song_id)
            dispatched += 1
        except Exception as exc:
            log.exception("Score backfill failed for generation %s — continuing", gen_id)
            if first_error is None:
                first_error = exc
    return BackfillResult(dispatched=dispatched, first_error=first_error)


async def score_backfill_loop(app: FastAPI) -> None:
    """Run the throttled score-backfill tick for the server lifetime.

    Uses a single-flight Redis lock so
    only one web replica dispatches a given tick's batch.
    """
    from songmaker_cli.arq_pool import get_arq_pool
    from songmaker_cli.constants import (
        SCORE_BACKFILL_INTERVAL_SECONDS,
        SCORE_BACKFILL_LOCK_KEY,
        SCORE_BACKFILL_LOCK_TTL_SECONDS,
    )

    ctx: AppContext = app.state.ctx
    registry = background_loop_registry(app)
    while True:
        await asyncio.sleep(SCORE_BACKFILL_INTERVAL_SECONDS)
        try:
            acquired = await asyncio.to_thread(
                ctx.redis.set,
                SCORE_BACKFILL_LOCK_KEY, "1",
                ex=SCORE_BACKFILL_LOCK_TTL_SECONDS, nx=True,
            )
            if not acquired:
                registry.record_success(BackgroundLoopName.SCORE_BACKFILL)
                continue
            result = await backfill_unscored_generations(ctx, get_arq_pool())
            if result.first_error is not None:
                registry.record_failure(BackgroundLoopName.SCORE_BACKFILL, result.first_error)
            else:
                registry.record_success(BackgroundLoopName.SCORE_BACKFILL)
            if result.dispatched:
                log.info("Score backfill: dispatched %d generation(s)", result.dispatched)
        except Exception as exc:
            registry.record_failure(BackgroundLoopName.SCORE_BACKFILL, exc)
            log.exception("Score backfill tick failed")


def read_worker_liveness(ctx: AppContext) -> dict[JobType, WorkerLiveness]:
    """Read lifecycle liveness after the database owner supplies the registry."""
    from songmaker_cli.db.queries.workers import list_worker_identities

    with ctx.db() as session:
        worker_ids = [worker.id for worker in list_worker_identities(session)]
    return read_liveness_signals(ctx.redis, worker_ids)


def reap_stale_jobs(
    ctx: AppContext,
    *,
    now: datetime | None = None,
    worker_liveness: Mapping[JobType, WorkerLiveness] | None = None,
) -> int:
    """Terminalize every stale job according to the shared type table."""
    from songmaker_cli.db.queries.jobs import recover_stale_jobs_by_age_and_type

    if worker_liveness is None:
        worker_liveness = read_worker_liveness(ctx)
    with ctx.db() as session:
        recovered = recover_stale_jobs_by_age_and_type(
            session, now=now, worker_liveness=worker_liveness,
        )
        session.commit()
    recovered_count = sum(recovered.values())
    if recovered_count:
        log.warning("Recovered %d stale job(s)", recovered_count)
    return recovered_count


def reconcile_crashed_loras(ctx: AppContext) -> int:
    """Mark LoRAs stuck in active statuses as FAILED when their job is terminal.

    Runs at web-process startup and on every :func:`stale_job_reaper_loop`
    tick. If the ARQ worker crashed mid-training, the LoRA row stays in
    PREPROCESSING / TRAINING / EXPORTING even though no job is running. It
    delegates locked, per-LoRA database reconciliation and post-commit
    filesystem cleanup to the LoRA job owner after the lifecycle reaper has
    terminalized its job.

    Returns the number of rows reconciled.
    """
    from songmaker_cli.jobs.lora_training import reconcile_crashed_loras as reconcile

    reconciled = reconcile(ctx.db, ctx.audio_dir)
    if reconciled:
        log.info("Reconciled %d crashed LoRA(s)", reconciled)
    return reconciled


def _run_stale_job_reaper_tick(
    ctx: AppContext, *, now: datetime | None = None,
) -> tuple[int, int]:
    """Reap all stale jobs and reconcile crashed LoRAs for one tick.

    Returns ``(jobs_recovered, loras_reconciled)``.
    """
    recovered_jobs = reap_stale_jobs(ctx, now=now)
    reconciled_loras = reconcile_crashed_loras(ctx)
    return recovered_jobs, reconciled_loras


async def stale_job_reaper_loop(app: FastAPI) -> None:
    """Run stale-job reaping and LoRA reconciliation for the server lifetime.

    The lifecycle loop is the one periodic job-reaper owner. It uses the same
    single-flight Redis lock idiom as ``score_backfill_loop`` so one web replica handles each tick.
    """
    ctx: AppContext = app.state.ctx
    registry = background_loop_registry(app)
    while True:
        await asyncio.sleep(JOB_REAPER_INTERVAL_SECONDS)
        try:
            acquired = await asyncio.to_thread(
                ctx.redis.set,
                JOB_REAPER_LOCK_KEY, "1",
                ex=JOB_REAPER_LOCK_TTL_SECONDS, nx=True,
            )
            if not acquired:
                registry.record_success(BackgroundLoopName.STALE_JOB_REAPER)
                continue
            await asyncio.to_thread(_run_stale_job_reaper_tick, ctx)
        except Exception as exc:
            registry.record_failure(BackgroundLoopName.STALE_JOB_REAPER, exc)
            log.exception("Stale job reaper tick failed")
        else:
            registry.record_success(BackgroundLoopName.STALE_JOB_REAPER)


def _cleanup_sessions(ctx: AppContext) -> int:
    """Commit expired-session removal without changing surviving sessions."""
    from songmaker_cli.db.queries.auth import delete_expired_sessions

    with ctx.db() as db:
        purged = delete_expired_sessions(db)
        db.commit()
    return purged


async def session_cleanup_loop(
    app: FastAPI, *, wait: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    from songmaker_cli.constants import SESSION_CLEANUP_INTERVAL_SECONDS

    ctx: AppContext = app.state.ctx
    registry = background_loop_registry(app)

    while True:
        await wait(SESSION_CLEANUP_INTERVAL_SECONDS)
        try:
            purged = await asyncio.to_thread(_cleanup_sessions, ctx)
            if purged:
                log.info("Session cleanup: purged %d expired sessions from DB", purged)
        except Exception as exc:
            consecutive_failures = registry.record_failure(BackgroundLoopName.SESSION_CLEANUP, exc)
            if consecutive_failures >= BACKGROUND_LOOP_FAILURE_THRESHOLD:
                log.exception(
                    "Session cleanup failed %d consecutive times",
                    consecutive_failures,
                )
            else:
                log.warning("Session cleanup failed", exc_info=True)
        else:
            registry.record_success(BackgroundLoopName.SESSION_CLEANUP)
