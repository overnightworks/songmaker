"""Health signals shared by runtime owners and API responses."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Literal

from songmaker_cli.constants import BACKGROUND_LOOP_FAILURE_THRESHOLD


class BackgroundLoopName(StrEnum):
    COVER_RUNNER = "cover_runner"
    SESSION_CLEANUP = "session_cleanup"
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


type CodexImageSandboxRuntimeHealth = Literal["ready", "not_set_up", "unverified"]
