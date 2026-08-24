"""Application lifecycle helpers -- admin auto-setup and session sync."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Final

from arq.connections import ArqRedis
from fastapi import FastAPI
from sqlalchemy.orm import Session

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import (
    RESOURCE_EVENT_CLEANUP_INTERVAL_SECONDS,
    RESOURCE_EVENT_RETENTION_DAYS,
)
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

QUEUE_STREAM_CLEANUP_INTERVAL_SECONDS: Final = 4 * 60 * 60
_QUEUE_STREAM_CLEANUP_EVERY_N_TICKS: Final = max(
    1, QUEUE_STREAM_CLEANUP_INTERVAL_SECONDS // RESOURCE_EVENT_CLEANUP_INTERVAL_SECONDS
)


def cleanup_expired_resource_events(ctx: AppContext) -> int:
    """Delete delivered event history beyond retention, preserving cursors."""
    from songmaker_cli.db.queries import delete_resource_events_before

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
    tick = 0
    while True:
        await asyncio.sleep(RESOURCE_EVENT_CLEANUP_INTERVAL_SECONDS)
        tick += 1
        try:
            await asyncio.to_thread(cleanup_expired_resource_events, ctx)
        except Exception:
            log.exception("Resource event cleanup failed")

        if tick % _QUEUE_STREAM_CLEANUP_EVERY_N_TICKS == 0:
            try:
                await asyncio.to_thread(cleanup_expired_queue_streams, ctx)
            except Exception:
                log.exception("Queue stream cleanup failed")


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


async def backfill_unscored_generations(ctx: AppContext, redis: ArqRedis) -> int:
    """Auto-score one throttled batch of generations that still have no score.

    Covers both a generation that predates auto-scoring and one an earlier
    auto-score attempt could not reach (worker down, enqueue failure) — both
    look identical here: no ``Score`` row yet. Each generation is handled
    independently so one bad row cannot stop the rest of the batch.
    """
    from songmaker_cli.constants import SCORE_BACKFILL_BATCH_SIZE
    from songmaker_cli.jobs import _auto_score_generation

    with ctx.db() as session:
        candidates = _pick_unscored_generations(session, SCORE_BACKFILL_BATCH_SIZE)

    scored = 0
    for gen_id, song_id in candidates:
        try:
            await _auto_score_generation(redis, ctx.db, gen_id, song_id)
            scored += 1
        except Exception:
            log.exception("Score backfill failed for generation %s — continuing", gen_id)
    return scored


async def score_backfill_loop(app: FastAPI) -> None:
    """Run the throttled score-backfill tick for the server lifetime.

    Uses the same single-flight Redis lock idiom as ``session_sync_loop`` so
    only one web replica dispatches a given tick's batch.
    """
    from songmaker_cli.arq_pool import get_arq_pool
    from songmaker_cli.constants import (
        SCORE_BACKFILL_INTERVAL_SECONDS,
        SCORE_BACKFILL_LOCK_KEY,
        SCORE_BACKFILL_LOCK_TTL_SECONDS,
    )

    ctx: AppContext = app.state.ctx
    while True:
        await asyncio.sleep(SCORE_BACKFILL_INTERVAL_SECONDS)
        try:
            acquired = await asyncio.to_thread(
                ctx.redis.set,
                SCORE_BACKFILL_LOCK_KEY, "1",
                ex=SCORE_BACKFILL_LOCK_TTL_SECONDS, nx=True,
            )
            if not acquired:
                continue
            scored = await backfill_unscored_generations(ctx, get_arq_pool())
            if scored:
                log.info("Score backfill: dispatched %d generation(s)", scored)
        except Exception:
            log.exception("Score backfill tick failed")


def reconcile_crashed_loras(ctx: AppContext) -> int:
    """Mark LoRAs stuck in active statuses as FAILED when their job is terminal.

    Runs at web-process startup. If the ARQ worker crashed mid-training the
    LoRA row stays in PREPROCESSING / TRAINING / EXPORTING even though no
    job is running. We detect that the associated ``training_job_id`` is
    either missing or in a terminal state, and reuse the job runner's
    ``cleanup_failed_lora`` helper to release disk space and mark the row
    FAILED.

    Returns the number of rows reconciled.
    """
    from songmaker_cli.constants import JOB_TERMINAL_STATUSES
    from songmaker_cli.db.queries import get_job, list_active_user_loras
    from songmaker_cli.jobs.lora_training import cleanup_failed_lora

    reconciled = 0
    with ctx.db() as session:
        active = list_active_user_loras(session)
        victims: list[tuple[str, str]] = []
        for lora in active:
            if lora.training_job_id is None:
                victims.append((lora.id, lora.user_id))
                continue
            job = get_job(session, lora.training_job_id)
            if job is None or job.status in JOB_TERMINAL_STATUSES:
                victims.append((lora.id, lora.user_id))

    for lora_id, user_id in victims:
        cleanup_failed_lora(
            lora_id=lora_id, user_id=user_id, audio_dir=ctx.audio_dir,
            db_factory=ctx.db, error_message="Training crashed or was interrupted",
        )
        reconciled += 1
    if reconciled:
        log.info("Startup: reconciled %d crashed LoRA(s)", reconciled)
    return reconciled


def auto_setup_admin(ctx: AppContext) -> None:
    settings = get_settings()
    admin_user = settings.admin_username
    admin_pass = (
        settings.admin_password.get_secret_value() if settings.admin_password else None
    )
    if not admin_user or not admin_pass:
        return

    from sqlalchemy.exc import IntegrityError

    from songmaker_cli.auth import ROLE_ADMIN, check_password_strength, hash_password
    from songmaker_cli.db.queries import create_user, user_count

    with ctx.db() as session:
        if user_count(session) > 0:
            return
        try:
            check_password_strength(admin_pass)
        except ValueError:
            log.error("ADMIN_PASSWORD does not meet strength requirements -- skipping auto-setup")
            return
        try:
            create_user(session, admin_user, hash_password(admin_pass), role=ROLE_ADMIN)
            session.commit()
        except IntegrityError:
            session.rollback()
            log.info("Auto-setup: admin user already exists (concurrent startup)")
            return
        log.info("Auto-setup: admin user '%s' created from env vars", admin_user)


def _sync_sessions(ctx: AppContext, session_cache) -> int:
    """Sync Redis session TTLs to the database. Returns count of synced sessions.

    Removes cached sessions for inactive users or sessions missing from the DB.
    Also purges expired sessions from the database (they accumulate because Redis
    evicts them on TTL but the DB rows stay forever).
    """
    from songmaker_cli.db.models import User as UserModel
    from songmaker_cli.db.models import UserSession
    from songmaker_cli.db.queries import delete_expired_sessions

    active = session_cache.get_all_sessions()

    with ctx.db() as db:
        purged = delete_expired_sessions(db)
        if purged:
            log.info("Session sync: purged %d expired sessions from DB", purged)

        if not active:
            db.commit()
            return 0

        session_ids = [sid for sid, _ in active]
        ttl_by_id = {sid: ttl for sid, ttl in active}
        synced = 0

        db_sessions = (
            db.query(UserSession)
            .filter(UserSession.id.in_(session_ids))
            .all()
        )
        db_session_by_id = {s.id: s for s in db_sessions}
        found_user_ids = {s.user_id for s in db_sessions}

        inactive_user_ids: set[str] = set()
        if found_user_ids:
            inactive_users = (
                db.query(UserModel.id)
                .filter(
                    UserModel.id.in_(found_user_ids),
                    UserModel.is_active.is_(False),
                )
                .all()
            )
            inactive_user_ids = {u.id for u in inactive_users}

        for session_id in session_ids:
            user_session = db_session_by_id.get(session_id)
            if not user_session:
                cached = session_cache.get(session_id)
                if cached:
                    session_cache.delete(session_id, cached.user_id)
                continue
            if user_session.user_id in inactive_user_ids:
                session_cache.delete_user_sessions(user_session.user_id)
                continue
            ttl = ttl_by_id[session_id]
            real_expires = datetime.now(timezone.utc) + timedelta(seconds=ttl)
            user_session.expires_at = real_expires
            synced += 1
        db.commit()

    return synced


async def session_sync_loop(app: FastAPI) -> None:
    from songmaker_cli.constants import (
        REDIS_SESSION_SYNC_INTERVAL_SECONDS,
        SESSION_SYNC_LOCK_KEY,
        SESSION_SYNC_LOCK_TTL_SECONDS,
    )

    ctx: AppContext = app.state.ctx
    session_cache = app.state.session_cache

    consecutive_failures = 0
    while True:
        await asyncio.sleep(REDIS_SESSION_SYNC_INTERVAL_SECONDS)
        try:
            acquired = await asyncio.to_thread(
                ctx.redis.set,
                SESSION_SYNC_LOCK_KEY, "1",
                ex=SESSION_SYNC_LOCK_TTL_SECONDS, nx=True,
            )
            if not acquired:
                continue
            try:
                synced = await asyncio.to_thread(_sync_sessions, ctx, session_cache)
                consecutive_failures = 0
                if synced:
                    log.info("Session sync: updated %d sessions", synced)
            finally:
                await asyncio.to_thread(ctx.redis.delete, SESSION_SYNC_LOCK_KEY)
        except Exception:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                log.error(
                    "Session sync failed %d consecutive times",
                    consecutive_failures, exc_info=True,
                )
            else:
                log.warning("Session sync failed", exc_info=True)
