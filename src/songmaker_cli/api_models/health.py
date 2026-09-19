"""Public health response built from the current service signals."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field

from songmaker_cli.health_types import (
    BackgroundLoopHealth,
    BackgroundLoopName,
    BackgroundLoopStatus,
    CodexImageSandboxRuntimeHealth,
)

ClaudeCliToolSurface = Literal["ok", "drift", "unverified"]


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
    redis_session_cache_failures: int
    acestep: Literal["healthy", "unknown", "unhealthy"]
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

    @classmethod
    def from_signals(
        cls, *, db_ok: bool, redis_ok: bool, music_running: bool, scoring_running: bool,
        music_queue_depth: int, scoring_queue_depth: int, session_cache_failures: int,
        workers_total: int, workers_online: int, queue_depth_cap_reached: bool,
        uptime_seconds: int, claude_cli_tool_surface: ClaudeCliToolSurface,
        codex_image_sandbox_runtime: CodexImageSandboxRuntimeHealth,
        background_loops: Mapping[BackgroundLoopName, BackgroundLoopHealth],
    ) -> HealthResponse:
        acestep: Literal["healthy", "unknown", "unhealthy"]
        if workers_online > 0:
            acestep = "healthy"
        elif workers_total == 0:
            acestep = "unknown"
        else:
            acestep = "unhealthy"
        degraded = (
            not db_ok
            or (not music_running and not scoring_running)
            or not redis_ok
            or acestep == "unhealthy"
        )
        return cls(
            status="degraded" if degraded else "ok",
            music_worker="running" if music_running else "stopped",
            scoring_worker="running" if scoring_running else "stopped",
            music_queue_depth=music_queue_depth,
            scoring_queue_depth=scoring_queue_depth,
            db="ok" if db_ok else "error",
            redis="ok" if redis_ok else "error",
            redis_session_cache_failures=session_cache_failures,
            acestep=acestep,
            acestep_workers_total=workers_total,
            acestep_workers_online=workers_online,
            queue_depth_cap_reached=queue_depth_cap_reached,
            uptime_seconds=uptime_seconds,
            claude_cli_tool_surface=claude_cli_tool_surface,
            codex_image_sandbox_runtime=codex_image_sandbox_runtime,
            background_loops={
                name: BackgroundLoopResponse.from_health(health)
                for name, health in background_loops.items()
            },
        )
