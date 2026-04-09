"""Shared infrastructure for arq workers.

Provides the WorkerBase class subclassed by MusicWorker and ScoringWorker.
Owns DB engine lifecycle, stale-job recovery, orphan-file audit, and the
common arq startup/shutdown hooks.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import ClassVar

from arq.connections import RedisSettings

from songmaker_cli.constants import (
    AUDIO_ROOT,
    DATA_ROOT,
    JOB_TERMINAL_STATUSES,
    RECOVERY_LOCK_TTL_SECONDS,
    REDIS_URL_MISMATCH_WARNING,
)
from songmaker_cli.db.engine import init_db, resolve_database_url
from songmaker_cli.db.queries import get_job

log = logging.getLogger(__name__)

JOB_TIMEOUT_SECONDS = int(os.environ.get("ARQ_JOB_TIMEOUT", "900"))
DRAIN_TIMEOUT_SECONDS = int(os.environ.get("ARQ_DRAIN_TIMEOUT", "300"))
HEALTH_CHECK_INTERVAL_SECONDS = 30


def build_redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    )


class WorkerBase:
    """Base class for arq workers.

    Subclasses set the ClassVars (job_type, recovery_lock_key, queue_name,
    max_jobs) and add their own task methods. The instance owns the DB
    engine + factory and the stale-job recovery state.

    arq integration: instantiate once at module load, then expose the
    instance methods on a sibling WorkerSettings shim class so arq's
    inspection of `functions`, `on_startup`, `on_shutdown`, `cron_jobs`
    finds bound methods.
    """

    job_type: ClassVar[str]
    recovery_lock_key: ClassVar[str]
    queue_name: ClassVar[str]
    max_jobs: ClassVar[int]
    job_timeout: ClassVar[int] = JOB_TIMEOUT_SECONDS
    drain_timeout: ClassVar[int] = DRAIN_TIMEOUT_SECONDS
    health_check_interval: ClassVar[int] = HEALTH_CHECK_INTERVAL_SECONDS

    def __init__(self) -> None:
        self._db_engine = None
        self._db_factory = None
        self._db_lock = threading.Lock()
        self._import_time_redis_url = os.environ.get("REDIS_URL")

    def get_db_factory(self):
        with self._db_lock:
            if self._db_factory is None:
                self._db_factory = init_db(resolve_database_url())
                self._db_engine = self._db_factory.kw["bind"]
        return self._db_factory

    def audio_dir(self) -> Path:
        return Path(os.environ.get("AUDIO_DIR", AUDIO_ROOT))

    def data_dir(self) -> Path:
        return Path(os.environ.get("DATA_DIR", DATA_ROOT))

    def check_job_still_valid(self, job_id: str) -> bool:
        with self.get_db_factory()() as session:
            job = get_job(session, job_id)
            if not job or job.status in JOB_TERMINAL_STATUSES:
                return False
        return True

    async def on_startup(self, ctx) -> None:
        from songmaker_cli.config import find_project_root, load_env_file
        from songmaker_cli.logging_config import configure_logging

        project_root = find_project_root(Path.cwd()) or Path.cwd()
        load_env_file(project_root)
        configure_logging()

        current_redis_url = os.environ.get("REDIS_URL")
        if current_redis_url and current_redis_url != self._import_time_redis_url:
            log.warning(
                REDIS_URL_MISMATCH_WARNING.format(
                    env_value=current_redis_url,
                    import_value=self._import_time_redis_url
                    or "redis://localhost:6379/0",
                ),
            )

        log.info("%s worker starting up...", self.job_type)
        await self._recover_on_startup(ctx)
        log.info("%s worker ready", self.job_type)

    async def on_shutdown(self, ctx) -> None:
        from songmaker_cli.db.queries import recover_stale_jobs_by_type

        redis = ctx["redis"]
        if await redis.set(
            self.recovery_lock_key, "1", ex=RECOVERY_LOCK_TTL_SECONDS, nx=True,
        ):
            try:
                with self.get_db_factory()() as session:
                    recovered = recover_stale_jobs_by_type(session, self.job_type)
                    if recovered:
                        log.warning(
                            "Shutdown: marked %d in-progress %s jobs as failed",
                            recovered, self.job_type,
                        )
                    session.commit()
            finally:
                await redis.delete(self.recovery_lock_key)
        else:
            log.warning("Shutdown recovery skipped — another worker holds the lock")

        if self._db_engine is not None:
            self._db_engine.dispose()
            log.info("Database connection pool disposed")

    async def _recover_on_startup(self, ctx) -> int:
        from songmaker_cli.db.queries import recover_stale_jobs_by_type

        redis = ctx["redis"]
        if not await redis.set(
            self.recovery_lock_key, "1", ex=RECOVERY_LOCK_TTL_SECONDS, nx=True,
        ):
            log.info("Stale job recovery skipped — another worker holds the lock")
            return 0

        recovered = 0
        try:
            with self.get_db_factory()() as session:
                recovered = recover_stale_jobs_by_type(session, self.job_type)
                if recovered:
                    log.info("Recovered %d stale %s jobs", recovered, self.job_type)
                session.commit()
        finally:
            await redis.delete(self.recovery_lock_key)
        return recovered

    async def cleanup_stale_cron(self, ctx) -> int:
        """Periodic cleanup cron entrypoint.

        Subclasses can override and call ``await super().cleanup_stale_cron(ctx)``
        to extend with their own additional cleanup work.
        """
        from songmaker_cli.db.queries import recover_stale_jobs_by_age_and_type

        with self.get_db_factory()() as session:
            count = recover_stale_jobs_by_age_and_type(session, self.job_type)
            if count:
                session.commit()
        return count

    def audit_orphaned_files(self) -> None:
        """Log audio files on disk that have no matching DB record."""
        try:
            self._audit_orphaned_files_inner()
        except Exception:
            log.warning("Orphaned file audit failed", exc_info=True)

    def _audit_orphaned_files_inner(self) -> None:
        from songmaker_cli.db.queries import all_generation_paths

        audio_dir = self.audio_dir()
        if not audio_dir.exists():
            return

        with self.get_db_factory()() as session:
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
