"""Health responses built from the current service signals: the public status and the details."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from songmaker_cli.api_models.release import ReleaseInfo
from songmaker_cli.health_types import (
    BackgroundLoopHealth,
    BackgroundLoopName,
    BackgroundLoopStatus,
    CodexImageSandboxRuntimeHealth,
)

ClaudeCliToolSurface = Literal["ok", "drift", "unverified"]


@dataclass(frozen=True)
class HealthSignals:
    db_ok: bool
    redis_ok: bool
    music_running: bool
    scoring_running: bool
    music_queue_depth: int
    scoring_queue_depth: int
    workers_total: int
    workers_online: int
    workers_lm_failed: bool
    queue_depth_cap_reached: bool
    uptime_seconds: int
    claude_cli_tool_surface: ClaudeCliToolSurface
    codex_image_sandbox_runtime: CodexImageSandboxRuntimeHealth
    background_loops: Mapping[BackgroundLoopName, BackgroundLoopHealth]
    release: ReleaseInfo

    @property
    def acestep(self) -> Literal["healthy", "unknown", "unhealthy"]:
        if self.workers_online > 0:
            return "healthy"
        if self.workers_total == 0:
            return "unknown"
        return "unhealthy"

    @property
    def status(self) -> Literal["ok", "degraded"]:
        degraded = (
            not self.db_ok
            or (not self.music_running and not self.scoring_running)
            or not self.redis_ok
            or self.acestep == "unhealthy"
        )
        return "degraded" if degraded else "ok"


class HealthStatusResponse(BaseModel):
    """The readiness answer anyone may read; the details need the monitoring token."""

    status: Literal["ok", "degraded"]

    @classmethod
    def from_signals(cls, signals: HealthSignals) -> HealthStatusResponse:
        return cls(status=signals.status)


class BackgroundLoopResponse(BaseModel):
    state: BackgroundLoopStatus
    consecutive_failures: int
    last_error: str | None

    @classmethod
    def from_health(cls, health: BackgroundLoopHealth) -> BackgroundLoopResponse:
        return cls(
            state=health.status,
            consecutive_failures=health.consecutive_failures,
            last_error=health.last_error,
        )


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    music_worker: Literal["running", "stopped"]
    scoring_worker: Literal["running", "stopped"]
    music_queue_depth: int
    scoring_queue_depth: int
    db: Literal["ok", "error"]
    redis: Literal["ok", "error"]
    acestep: Literal["healthy", "unknown", "unhealthy"]
    acestep_reason: Literal["lm_init_failed"] | None = Field(description=(
        "lm_init_failed while a registered worker's language model cannot start, "
        "otherwise null; it can accompany a healthy aggregate when other workers are "
        "online. A fixed code; the worker, the mode and the vendor's error text stay in "
        "the worker log."
    ))
    acestep_workers_total: int
    acestep_workers_online: int
    queue_depth_cap_reached: bool
    uptime_seconds: int
    claude_cli_tool_surface: ClaudeCliToolSurface = Field(description=(
        "Whether the mounted Claude CLI tool surface matches the co-writer allowlist: "
        "ok, drift, or unverified. A drifted binary never takes the whole server down; "
        "the co-writer refuses it on its own, while monitoring can see this state "
        "without reading the boot log. This is the gate's live answer from "
        "provider.claude_cli_tool_surface_health(), updated by every "
        "verify_cli_tool_surface() call, cache hit or fresh probe alike. A later "
        "successful co-writer turn clears an earlier unverified state, and a later "
        "drifted build replaces an earlier ok. Before the boot check runs, the gate "
        "reports unverified, never a silent ok."
    ))
    codex_image_sandbox_runtime: CodexImageSandboxRuntimeHealth = Field(description=(
        "Whether the Codex cover-image sandbox user-namespace boot check last "
        "succeeded: ready, not_set_up, or unverified. This live value comes from "
        "lifecycle.codex_image_sandbox_runtime_health(), updated by every "
        "report_codex_image_sandbox_runtime() call, so a later boot report overrides "
        "an earlier one. Before the boot report runs, it reports unverified."
    ))
    background_loops: dict[BackgroundLoopName, BackgroundLoopResponse]
    release: ReleaseInfo

    @classmethod
    def from_signals(cls, signals: HealthSignals) -> HealthResponse:
        return cls(
            status=signals.status,
            music_worker="running" if signals.music_running else "stopped",
            scoring_worker="running" if signals.scoring_running else "stopped",
            music_queue_depth=signals.music_queue_depth,
            scoring_queue_depth=signals.scoring_queue_depth,
            db="ok" if signals.db_ok else "error",
            redis="ok" if signals.redis_ok else "error",
            acestep=signals.acestep,
            acestep_reason="lm_init_failed" if signals.workers_lm_failed else None,
            acestep_workers_total=signals.workers_total,
            acestep_workers_online=signals.workers_online,
            queue_depth_cap_reached=signals.queue_depth_cap_reached,
            uptime_seconds=signals.uptime_seconds,
            claude_cli_tool_surface=signals.claude_cli_tool_surface,
            codex_image_sandbox_runtime=signals.codex_image_sandbox_runtime,
            background_loops={
                name: BackgroundLoopResponse.from_health(health)
                for name, health in signals.background_loops.items()
            },
            release=signals.release,
        )
