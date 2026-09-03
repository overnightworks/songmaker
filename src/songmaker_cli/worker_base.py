"""Shared infrastructure for arq workers.

Provides the WorkerBase class subclassed by MusicWorker and ScoringWorker.
Owns DB engine lifecycle, stale-job recovery, orphan-file audit, and the
common arq startup/shutdown hooks.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import ClassVar

from arq.connections import RedisSettings

from songmaker_cli.constants import (
    JOB_ACTIVE_STATUSES,
    JOB_TERMINAL_STATUSES,
    RECOVERY_LOCK_TTL_SECONDS,
)
from songmaker_cli.db.engine import init_db
from songmaker_cli.db.queries import get_job
from songmaker_cli.settings import Settings, get_settings

log = logging.getLogger(__name__)

HEALTH_CHECK_INTERVAL_SECONDS = 30


def build_redis_settings(settings: Settings | None = None) -> RedisSettings:
    """Build arq RedisSettings from validated Settings."""
    return RedisSettings.from_dsn((settings or get_settings()).redis_url)


class WorkerBase:
    """Base class for arq workers.

    Subclasses set the ClassVars (job_types, recovery_lock_key, queue_name,
    max_jobs) and add their own task methods. The instance owns the DB
    engine + factory and the stale-job recovery state.

    arq integration: instantiate once at module load, then expose the
    instance methods on a sibling WorkerSettings shim class so arq's
    inspection of `functions`, `on_startup`, `on_shutdown`, `cron_jobs`
    finds bound methods.
    """

    job_types: ClassVar[tuple[str, ...]]
    recovery_lock_key: ClassVar[str]
    queue_name: ClassVar[str]
    max_jobs: ClassVar[int]
    health_check_interval: ClassVar[int] = HEALTH_CHECK_INTERVAL_SECONDS

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._db_engine = None
        self._db_factory = None
        self._db_lock = threading.Lock()

    @property
    def job_timeout(self) -> int:
        return self._settings.arq_job_timeout

    @property
    def drain_timeout(self) -> int:
        return self._settings.arq_drain_timeout

    def recovery_statuses_by_type(self) -> dict[str, frozenset[str]]:
        """Return statuses this worker may terminalize at restart boundaries."""
        return {job_type: JOB_ACTIVE_STATUSES for job_type in self.job_types}

    def worker_name(self) -> str:
        """Return the stable, human-readable name derived from owned job types."""
        return "+".join(self.job_types)

    def get_db_factory(self):
        with self._db_lock:
            if self._db_factory is None:
                self._db_factory = init_db(self._settings.database_url)
                self._db_engine = self._db_factory.kw["bind"]
        return self._db_factory

    def audio_dir(self) -> Path:
        return Path(self._settings.audio_dir)

    def data_dir(self) -> Path:
        return Path(self._settings.data_dir)

    def check_job_still_valid(self, job_id: str) -> bool:
        with self.get_db_factory()() as session:
            job = get_job(session, job_id)
            if not job or job.status in JOB_TERMINAL_STATUSES:
                return False
        return True

    async def on_startup(self, ctx) -> None:
        from songmaker_cli.logging_config import configure_logging

        configure_logging()

        log.info("%s worker starting up...", self.worker_name())
        await self._recover_on_startup(ctx)
        log.info("%s worker ready", self.worker_name())

    async def on_shutdown(self, ctx) -> None:
        from songmaker_cli.db.queries import recover_stale_jobs_by_type

        redis = ctx["redis"]
        if await redis.set(
            self.recovery_lock_key, "1", ex=RECOVERY_LOCK_TTL_SECONDS, nx=True,
        ):
            try:
                with self.get_db_factory()() as session:
                    recovered = recover_stale_jobs_by_type(
                        session, self.recovery_statuses_by_type(),
                    )
                    if recovered:
                        log.warning(
                            "Shutdown: marked %d in-progress %s jobs as failed",
                            sum(recovered.values()), self.worker_name(),
                        )
                    session.commit()
                await self._reconcile_recovered_jobs(recovered)
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

        recovered: dict[str, int] = {}
        try:
            with self.get_db_factory()() as session:
                recovered = recover_stale_jobs_by_type(
                    session, self.recovery_statuses_by_type(),
                )
                if recovered:
                    log.info(
                        "Recovered %d stale %s jobs",
                        sum(recovered.values()), self.worker_name(),
                    )
                session.commit()
            await self._reconcile_recovered_jobs(recovered)
        finally:
            await redis.delete(self.recovery_lock_key)
        return sum(recovered.values())

    async def cleanup_stale_cron(self, ctx) -> int:
        """Periodic cleanup cron entrypoint.

        Subclasses can override and call ``await super().cleanup_stale_cron(ctx)``
        to extend with their own additional cleanup work.
        """
        from songmaker_cli.db.queries import recover_stale_jobs_by_age_and_type

        with self.get_db_factory()() as session:
            recovered = recover_stale_jobs_by_age_and_type(
                session, self.job_types, return_counts=True,
            )
            if recovered:
                session.commit()
        await self._reconcile_recovered_jobs(recovered)
        return sum(recovered.values())

    async def _reconcile_recovered_jobs(self, recovered: dict[str, int]) -> None:
        """Run worker-specific cleanup after stale jobs become terminal."""

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
