"""Health signals shared by runtime owners and API responses."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Collection
from dataclasses import dataclass, replace
from enum import StrEnum
from time import monotonic

from songmaker_cli.constants import BACKGROUND_LOOP_FAILURE_THRESHOLD


class BackgroundLoopName(StrEnum):
    COVER_RUNNER = "cover_runner"
    SESSION_CLEANUP = "session_cleanup"
    RESOURCE_EVENT_CLEANUP = "resource_event_cleanup"
    SCORE_BACKFILL = "score_backfill"
    STALE_JOB_REAPER = "stale_job_reaper"
    OWNER_LEASE = "owner_lease"
    OWNER_LAPSES = "owner_lapses"
    OWNER_GONE_REAPER = "owner_gone_reaper"


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
        self._shutdown_began_at: float | None = None
        self._shutdown_begun = asyncio.Event()

    @property
    def shutting_down(self) -> bool:
        return self._shutdown_began_at is not None

    def begin_shutdown(self) -> None:
        """Start the process's shutdown; a second call keeps the first one's start."""
        if self._shutdown_began_at is None:
            self._shutdown_began_at = monotonic()
            self._shutdown_begun.set()

    def seconds_since_shutdown_began(self) -> float:
        if self._shutdown_began_at is None:
            return 0.0
        return monotonic() - self._shutdown_began_at

    async def ending_at_shutdown(self, frames: AsyncGenerator[str, None]) -> AsyncGenerator[str, None]:
        """Relay ``frames`` until the shutdown begins, then close them at once."""
        begun = asyncio.ensure_future(self._shutdown_begun.wait())
        next_frame: asyncio.Future[str] | None = None
        try:
            while True:
                next_frame = asyncio.ensure_future(anext(frames))
                await asyncio.wait({next_frame, begun}, return_when=asyncio.FIRST_COMPLETED)
                if not next_frame.done():
                    return
                try:
                    frame = next_frame.result()
                except StopAsyncIteration:
                    return
                yield frame
        finally:
            begun.cancel()
            if next_frame is not None and not next_frame.done():
                next_frame.cancel()
                await asyncio.wait({next_frame})
            await frames.aclose()

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
