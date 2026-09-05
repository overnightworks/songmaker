"""Application lifecycle helpers -- admin auto-setup and session sync."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Final, Literal

from arq.connections import ArqRedis
from fastapi import FastAPI
from sqlalchemy.orm import Session

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import (
    BACKGROUND_LOOP_FAILURE_THRESHOLD,
    JOB_REAPER_INTERVAL_SECONDS,
    REDIS_KEY_PREFIX,
    RESOURCE_EVENT_CLEANUP_INTERVAL_SECONDS,
    RESOURCE_EVENT_RETENTION_DAYS,
    JobType,
)
from songmaker_cli.settings import get_settings
from songmaker_cli.worker_liveness import WorkerLiveness
from songmaker_cli.worker_liveness import read_worker_liveness as read_liveness_signals

log = logging.getLogger(__name__)

QUEUE_STREAM_CLEANUP_INTERVAL_SECONDS: Final = 4 * 60 * 60
_QUEUE_STREAM_CLEANUP_EVERY_N_TICKS: Final = max(
    1, QUEUE_STREAM_CLEANUP_INTERVAL_SECONDS // RESOURCE_EVENT_CLEANUP_INTERVAL_SECONDS
)
_CODEX_STARTUP_PROBE_BWRAP_ARGUMENTS: Final = (
    "--unshare-user",
    "--unshare-net",
    "--ro-bind", "/", "/",
    "/bin/true",
)

# The web process owns stale-job recovery for every job type.
JOB_REAPER_LOCK_KEY: Final = f"{REDIS_KEY_PREFIX}:job_reaper_lock"
JOB_REAPER_LOCK_TTL_SECONDS: Final = 60

class BackgroundLoopName(StrEnum):
    COVER_RUNNER = "cover_runner"
    SESSION_SYNC = "session_sync"
    RESOURCE_EVENT_CLEANUP = "resource_event_cleanup"
    SCORE_BACKFILL = "score_backfill"
    STALE_JOB_REAPER = "stale_job_reaper"
    PROVIDER_STATUS_REFRESH = "provider_status_refresh"


class BackgroundLoopStatus(StrEnum):
    OK = "ok"
    FAILING = "failing"
    DEAD = "dead"


@dataclass
class BackgroundLoopHealth:
    name: BackgroundLoopName
    consecutive_failures: int = 0
    last_error: str | None = None
    is_alive: bool = True

    @property
    def status(self) -> BackgroundLoopStatus:
        if not self.is_alive:
            return BackgroundLoopStatus.DEAD
        if self.consecutive_failures >= BACKGROUND_LOOP_FAILURE_THRESHOLD:
            return BackgroundLoopStatus.FAILING
        return BackgroundLoopStatus.OK


class BackgroundLoopRegistry:
    def __init__(self, loop_names: Collection[BackgroundLoopName] | None = None) -> None:
        self._loops = {
            name: BackgroundLoopHealth(name=name)
            for name in (loop_names or BackgroundLoopName)
        }
        self._shutting_down = False

    @property
    def shutting_down(self) -> bool:
        return self._shutting_down

    def begin_shutdown(self) -> None:
        self._shutting_down = True

    def record_success(self, name: BackgroundLoopName) -> None:
        health = self._loops[name]
        health.consecutive_failures = 0
        health.last_error = None

    def record_failure(self, name: BackgroundLoopName, error: Exception) -> int:
        health = self._loops[name]
        health.consecutive_failures += 1
        health.last_error = type(error).__name__
        return health.consecutive_failures

    def mark_dead(self, name: BackgroundLoopName, error: BaseException | None) -> None:
        health = self._loops[name]
        health.is_alive = False
        health.last_error = "task ended" if error is None else type(error).__name__

    def loop_health(self) -> dict[BackgroundLoopName, BackgroundLoopHealth]:
        """Return copies of the current health for each registered loop."""
        return {name: replace(health) for name, health in self._loops.items()}


def background_loop_registry(app: FastAPI) -> BackgroundLoopRegistry:
    return app.state.background_loop_registry


def _codex_image_sandbox_runtime_error() -> str | None:
    bubblewrap = shutil.which("bwrap")
    if bubblewrap is None:
        return "bubblewrap is not installed"
    try:
        result = subprocess.run(
            (
                bubblewrap,
                *_CODEX_STARTUP_PROBE_BWRAP_ARGUMENTS,
            ),
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "bubblewrap user namespaces are unavailable"
    if result.returncode != 0:
        return "bubblewrap user namespaces are unavailable"
    return None


def report_codex_image_sandbox_runtime() -> Literal["ready", "not_set_up"]:
    """Report whether the future web cover route can enter its user namespace."""
    error = _codex_image_sandbox_runtime_error()
    if error is not None:
        log.info("Codex cover image path not set up: %s", error)
        return "not_set_up"
    log.info("Codex cover image sandbox runtime verified")
    return "ready"


async def provider_status_refresh_loop(app: FastAPI) -> None:
    """Refresh provider reachability and catalogs outside request handling."""
    from songmaker_cli.constants import CLI_LOGIN_STATUS_CACHE_SECONDS, COWRITER_PROVIDERS
    from songmaker_cli.cowriter.catalog import refresh_provider_snapshot

    registry = background_loop_registry(app)
    while True:
        error: Exception | None = None
        for provider in COWRITER_PROVIDERS:
            try:
                await asyncio.to_thread(refresh_provider_snapshot, provider)
            except Exception as exc:
                if error is None:
                    error = exc
                log.exception("Provider status refresh failed for %s", provider)
        if error is None:
            registry.record_success(BackgroundLoopName.PROVIDER_STATUS_REFRESH)
        else:
            registry.record_failure(BackgroundLoopName.PROVIDER_STATUS_REFRESH, error)
        await asyncio.sleep(CLI_LOGIN_STATUS_CACHE_SECONDS)


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


def _decode_redis_value(value: bytes | str | None) -> str | None:
    """Normalize a raw Redis reply: the production ``ArqRedis`` pool returns
    bytes (no ``decode_responses``), while a test double may already hand
    back ``str``."""
    if isinstance(value, bytes):
        return value.decode()
    return value


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
        if (decoded := _decode_redis_value(raw_count)) is not None
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
    tracked_ids = [_decode_redis_value(gen_id) for gen_id in tracked_raw]

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
    from songmaker_cli.db.queries import list_worker_identities

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
    from songmaker_cli.db.queries import recover_stale_jobs_by_age_and_type

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
    single-flight Redis lock idiom as ``session_sync_loop`` /
    ``score_backfill_loop`` so one web replica handles each tick.
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


async def report_claude_cli_tool_surface() -> Literal["ok", "drift", "unverified"]:
    """Verify the mounted Claude CLI's tool surface at boot; say so in the
    log, and return the state for ``/health``'s ``claude_cli_tool_surface``
    field (operator ruling, #351 round 6).

    #351 originally asked for an unexpected tool to fail the server
    start outright; the operator overruled that once the allowlist gate
    itself was confirmed to cover every call path — a server that refuses
    to serve albums and playback over a co-writer problem is a worse
    outage than the co-writer being unavailable. So this never aborts
    startup. The co-writer's own CLI transport verifies this again itself
    and refuses a drifted binary regardless of what this function
    returns; this only makes that state visible to the operator and to
    monitoring, not just to whichever musician opens a chat first and
    finds it broken.

    Three states, not two — "could not check" is its own message to the
    operator, not silently folded into either verified state:

    - ``"ok"``: verified, and the surface matches the allowlist.
    - ``"drift"``: verified, and it does not (``CliToolSurfaceError``) — a
      real security finding.
    - ``"unverified"``: the probe itself failed to reach a verdict at all
      (no CLI mounted, a timeout, a zombie process, the MCP connection
      never coming up) — a different kind of unavailability, not evidence
      of drift, but also not the same claim as "checked and clean".
    """
    from songmaker_cli.claude.provider import (
        CliToolSurfaceError,
        UnavailableError,
        verify_cli_tool_surface,
    )

    try:
        await verify_cli_tool_surface()
    except CliToolSurfaceError as exc:
        log.exception("Claude CLI co-writer disabled: %s", exc)
        return "drift"
    except UnavailableError as exc:
        log.info("Claude CLI tool surface not verified: %s", exc)
        return "unverified"
    log.info("Claude CLI tool surface verified: songmaker MCP tools only")
    return "ok"


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
        ttl_by_id = dict(active)
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
    registry = background_loop_registry(app)

    while True:
        await asyncio.sleep(REDIS_SESSION_SYNC_INTERVAL_SECONDS)
        try:
            acquired = await asyncio.to_thread(
                ctx.redis.set,
                SESSION_SYNC_LOCK_KEY, "1",
                ex=SESSION_SYNC_LOCK_TTL_SECONDS, nx=True,
            )
            if not acquired:
                registry.record_success(BackgroundLoopName.SESSION_SYNC)
                continue
            try:
                synced = await asyncio.to_thread(_sync_sessions, ctx, session_cache)
                if synced:
                    log.info("Session sync: updated %d sessions", synced)
            finally:
                await asyncio.to_thread(ctx.redis.delete, SESSION_SYNC_LOCK_KEY)
        except Exception as exc:
            consecutive_failures = registry.record_failure(BackgroundLoopName.SESSION_SYNC, exc)
            if consecutive_failures >= BACKGROUND_LOOP_FAILURE_THRESHOLD:
                log.exception(
                    "Session sync failed %d consecutive times",
                    consecutive_failures,
                )
            else:
                log.warning("Session sync failed", exc_info=True)
        else:
            registry.record_success(BackgroundLoopName.SESSION_SYNC)
