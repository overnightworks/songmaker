"""Shared infrastructure for arq workers.

Provides the WorkerBase class subclassed by MusicWorker and ScoringWorker.
Owns DB engine lifecycle, the worker's owner lease, orphan-file audit, and the
common arq startup/shutdown hooks. A web process fails the jobs of a worker
whose lease is gone; no worker fails another's jobs.
"""

from __future__ import annotations

import logging
import threading
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from typing import ClassVar

from redis.asyncio import Redis as AsyncRedis

from songmaker_cli.constants import ARQ_HEALTH_CHECK_INTERVAL_SECONDS
from songmaker_cli.db.database_url import connection_url_from_settings
from songmaker_cli.db.engine import init_db
from songmaker_cli.db.queries.jobs import get_job
from songmaker_cli.job_types import JOB_TERMINAL_STATUSES
from songmaker_cli.redis_client import create_async_redis
from songmaker_cli.settings import Settings, get_settings
from songmaker_cli.worker_liveness import keep_owner_lease, owner_leases

log = logging.getLogger(__name__)


class WorkerBase:
    """Base class for arq workers.

    Subclasses set the ClassVars (job_types, queue_name, max_jobs) and add
    their own task methods. The instance owns the DB engine + factory and the
    process's owner id: its jobs carry the id from the moment they run, and its
    lease says the process lives.

    arq integration: instantiate once at module load, then expose the
    instance methods on a sibling WorkerSettings shim class so arq's
    inspection of `functions`, `on_startup`, `on_shutdown`, `cron_jobs`
    finds bound methods.
    """

    job_types: ClassVar[tuple[str, ...]]
    queue_name: ClassVar[str]
    max_jobs: ClassVar[int]
    health_check_interval: ClassVar[int] = ARQ_HEALTH_CHECK_INTERVAL_SECONDS

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._db_engine = None
        self._db_factory = None
        self._db_lock = threading.Lock()
        self.owner_id = str(uuid.uuid4())
        self._owner_redis: AsyncRedis | None = None
        self._lease_stack: AsyncExitStack | None = None

    def worker_name(self) -> str:
        """Return the stable, human-readable name derived from owned job types."""
        return "+".join(self.job_types)

    def get_db_factory(self):
        with self._db_lock:
            if self._db_factory is None:
                self._db_factory = init_db(connection_url_from_settings(self._settings))
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
        # Opening the database may wait for it to start; the lease says "alive" only after.
        self.get_db_factory()
        await self._start_owner_lease()
        log.info("%s worker ready", self.worker_name())

    async def on_shutdown(self, ctx) -> None:
        if self._lease_stack is not None:
            await self._release_owner_lease()

        if self._db_engine is not None:
            self._db_engine.dispose()
            log.info("Database connection pool disposed")

    async def _start_owner_lease(self) -> None:
        """Say this process lives, on a client of its own: arq's has no retry and no timeouts."""
        self._owner_redis = create_async_redis(self._settings.redis_url)
        self._lease_stack = AsyncExitStack()
        try:
            await self._lease_stack.enter_async_context(
                keep_owner_lease(owner_leases(self._owner_redis), self.owner_id),
            )
        except BaseException:
            await self._owner_redis.aclose()
            raise

    async def _release_owner_lease(self) -> None:
        """End the lease so a web process fails this worker's jobs within one tick."""
        await self._lease_stack.aclose()
        await self._owner_redis.aclose()

    def audit_orphaned_files(self) -> None:
        """Log audio files on disk that have no matching DB record."""
        try:
            self._audit_orphaned_files_inner()
        except Exception:
            log.warning("Orphaned file audit failed", exc_info=True)

    def _audit_orphaned_files_inner(self) -> None:
        from songmaker_cli.db.queries.generations import all_generation_paths

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
