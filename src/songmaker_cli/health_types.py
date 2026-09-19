"""Health signals shared by runtime owners and API responses."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from songmaker_cli.constants import BACKGROUND_LOOP_FAILURE_THRESHOLD


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


type CodexImageSandboxRuntimeHealth = Literal["ready", "not_set_up", "unverified"]
