"""Shared infrastructure for arq workers.

Provides DB singleton, timeout constants, terminal statuses,
and common startup/shutdown logic used by both music and scoring workers.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from arq.connections import RedisSettings

from songmaker_cli.constants import (
    AUDIO_ROOT,
    DATA_ROOT,
    RECOVERY_LOCK_TTL_SECONDS,
    REDIS_URL_MISMATCH_WARNING,
)
from songmaker_cli.db.engine import init_db, resolve_database_url
from songmaker_cli.db.queries import get_job

log = logging.getLogger(__name__)

_db_factory = None
_db_engine = None
_db_lock = threading.Lock()

JOB_TIMEOUT_SECONDS = int(os.environ.get("ARQ_JOB_TIMEOUT", "300"))
DRAIN_TIMEOUT_SECONDS = int(os.environ.get("ARQ_DRAIN_TIMEOUT", "300"))
HEALTH_CHECK_INTERVAL_SECONDS = 30
TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "cancelled"})


def _get_db_factory():
    global _db_factory, _db_engine
    with _db_lock:
        if _db_factory is None:
            _db_factory = init_db(resolve_database_url())
            _db_engine = _db_factory.kw["bind"]
    return _db_factory


def _audio_dir() -> Path:
    return Path(os.environ.get("AUDIO_DIR", AUDIO_ROOT))


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", DATA_ROOT))


def check_job_still_valid(job_id: str) -> bool:
    db_factory = _get_db_factory()
    with db_factory() as session:
        job = get_job(session, job_id)
        if not job or job.status in TERMINAL_STATUSES:
            return False
    return True


async def common_startup(ctx, import_time_redis_url: str | None) -> None:
    from songmaker_cli.config import find_project_root, load_env_file
    from songmaker_cli.logging_config import configure_logging

    project_root = find_project_root(Path.cwd()) or Path.cwd()
    load_env_file(project_root)
    configure_logging()

    current_redis_url = os.environ.get("REDIS_URL")
    if current_redis_url and current_redis_url != import_time_redis_url:
        log.warning(
            REDIS_URL_MISMATCH_WARNING.format(
                env_value=current_redis_url,
                import_value=import_time_redis_url or "redis://localhost:6379/0",
            ),
        )


async def common_shutdown(recovery_lock_key: str, job_type: str, redis) -> None:
    from songmaker_cli.db.queries import recover_stale_jobs_by_type

    if await redis.set(recovery_lock_key, "1", ex=RECOVERY_LOCK_TTL_SECONDS, nx=True):
        try:
            db_factory = _get_db_factory()
            with db_factory() as session:
                recovered = recover_stale_jobs_by_type(session, job_type)
                if recovered:
                    log.warning(
                        "Shutdown: marked %d in-progress %s jobs as failed",
                        recovered, job_type,
                    )
                session.commit()
        finally:
            await redis.delete(recovery_lock_key)
    else:
        log.warning("Shutdown recovery skipped — another worker holds the lock")

    if _db_engine is not None:
        _db_engine.dispose()
        log.info("Database connection pool disposed")


async def recover_on_startup(ctx, lock_key: str, job_type: str) -> int:
    from songmaker_cli.db.queries import recover_stale_jobs_by_type

    redis = ctx["redis"]
    if not await redis.set(lock_key, "1", ex=RECOVERY_LOCK_TTL_SECONDS, nx=True):
        log.info("Stale job recovery skipped — another worker holds the lock")
        return 0

    try:
        db_factory = _get_db_factory()
        with db_factory() as session:
            recovered = recover_stale_jobs_by_type(session, job_type)
            if recovered:
                log.info("Recovered %d stale %s jobs", recovered, job_type)
            session.commit()
    finally:
        await redis.delete(lock_key)
    return recovered


def make_cleanup_cron(job_type: str):
    async def _cleanup_stale(ctx):
        from songmaker_cli.db.queries import recover_stale_jobs_by_age_and_type

        db_factory = _get_db_factory()
        with db_factory() as session:
            count = recover_stale_jobs_by_age_and_type(session, job_type)
            if count:
                session.commit()
        return count

    return _cleanup_stale


def audit_orphaned_files() -> None:
    """Log audio files on disk that have no matching DB record."""
    try:
        _audit_orphaned_files_inner()
    except Exception:
        log.warning("Orphaned file audit failed", exc_info=True)


def _audit_orphaned_files_inner() -> None:
    from songmaker_cli.db.queries import all_generation_paths

    audio_dir = _audio_dir()
    if not audio_dir.exists():
        return

    db_factory = _get_db_factory()
    with db_factory() as session:
        known_paths = all_generation_paths(session)

    orphans: list[Path] = []
    for user_dir in audio_dir.iterdir():
        if not user_dir.is_dir():
            continue
        for audio_file in user_dir.iterdir():
            if audio_file.suffix not in (".mp3", ".wav"):
                continue
            rel = f"{user_dir.name}/{audio_file.name}"
            if rel not in known_paths:
                orphans.append(audio_file)

    if orphans:
        log.warning(
            "Found %d orphaned audio files (no DB record): %s",
            len(orphans),
            ", ".join(str(f) for f in orphans[:10]),
        )


def build_redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    )
