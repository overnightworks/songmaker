"""Typed application settings — single source of truth for env config.

Reads ``.server.env`` (project root) automatically via pydantic-settings.
Constructed lazily via ``get_settings()`` on first call (lru_cached).

Workers that need import-time access (arq's ``WorkerSettings`` class
inspects ``redis_settings`` / ``max_jobs`` / ``queue_name`` at module
load) MUST call ``get_settings()`` before defining their settings shim.

Tests construct ``Settings(...)`` directly with explicit kwargs and bypass
``get_settings()`` (or override the lru_cache).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    """Walk up from CWD to find .server.env at the project root.

    Honors ``SONGMAKER_SKIP_ENV_FILE=1`` to bypass loading entirely
    (used by the test suite so .server.env values do not leak into
    monkeypatched env tests).
    """
    import os as _os
    if _os.environ.get("SONGMAKER_SKIP_ENV_FILE") == "1":
        return None
    cwd = Path.cwd().resolve()
    for parent in (cwd, *cwd.parents):
        candidate = parent / ".server.env"
        if candidate.exists():
            return candidate
        if (parent / "pyproject.toml").exists():
            return None
    return None


class Settings(BaseSettings):
    """Validated application settings, loaded from env + .server.env.

    All env reads in ``src/songmaker_cli`` and ``src/acestep_worker`` go
    through this class. Required fields raise at startup if missing.
    Optional fields have explicit, named defaults that are visible in
    code review (no fallback chains, no sentinel coercion).
    """

    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Required (no defaults — startup fails if missing) ─────────────
    database_url: str
    redis_url: str
    session_secret: SecretStr
    songmaker_internal_token: SecretStr

    # ── HTTP server ───────────────────────────────────────────────────
    host: str = "127.0.0.1"
    request_timeout_seconds: int = Field(default=30, alias="REQUEST_TIMEOUT")
    allowed_hosts: str = ""
    cors_origin: str | None = None
    trusted_proxies: str = ""
    max_request_body_bytes: int = 1_048_576
    max_upload_body_bytes: int = 52_428_800

    # ── Logging ───────────────────────────────────────────────────────
    log_format: Literal["text", "json"] = "text"
    log_level: str = "INFO"

    # ── Database ──────────────────────────────────────────────────────
    database_pool_size: int = 5
    database_max_overflow: int = 10

    # ── Sessions / auth ───────────────────────────────────────────────
    session_max_age_seconds: int = Field(default=60 * 60 * 24 * 30, alias="SESSION_MAX_AGE")
    session_absolute_max_age_seconds: int = Field(
        default=60 * 60 * 24 * 90, alias="SESSION_ABSOLUTE_MAX_AGE",
    )
    login_rate_limit: int = 5
    login_lockout_threshold: int = 15
    login_lockout_window_seconds: int = Field(default=3600, alias="LOGIN_LOCKOUT_WINDOW")

    # ── Rate limits ───────────────────────────────────────────────────
    generation_rate_limit_user: int = 3
    generation_rate_limit_admin: int = 30
    scoring_rate_limit_user: int = 10
    scoring_rate_limit_admin: int = 100
    chat_rate_limit_user: int = 30
    chat_rate_limit_admin: int = 300
    max_queue_depth: int = 100
    max_user_active_jobs: int = 10
    ip_rate_limit: int = 120

    # ── arq workers ───────────────────────────────────────────────────
    arq_job_timeout: int = 900
    arq_drain_timeout: int = 300
    music_max_jobs: int = 2
    scoring_max_jobs: int = 1
    scoring_device: str = "cpu"
    stale_job_threshold_seconds: int = 360

    # ── Soft delete ───────────────────────────────────────────────────
    soft_delete_retention_days: int = 30

    # ── Claude ────────────────────────────────────────────────────────
    claude_chat_model: str = "claude-opus-4-6"
    claude_scoring_model: str = "claude-opus-4-6"
    anthropic_api_key: SecretStr | None = None

    # ── Admin auto-setup ──────────────────────────────────────────────
    admin_username: str | None = None
    admin_password: SecretStr | None = None

    # ── Filesystem roots (override via env for Docker volume mounts) ──
    audio_dir: str = "data/audio"
    data_dir: str = "data"


class WorkerSettings(BaseSettings):
    """Settings for the acestep-worker container.

    Independent from ``Settings`` because the GPU worker pod has no
    database, no sessions, and no internal API of its own — it only
    needs Redis, its own identity, and subprocess knobs. Inheriting
    from ``Settings`` would force the worker container to set
    ``DATABASE_URL`` and ``SESSION_SECRET`` for no reason.
    """

    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    worker_id: str
    redis_url: str
    songmaker_internal_token: SecretStr = SecretStr("")
    worker_host: str | None = None
    worker_port: int = 8001
    vram_budget_gb: float = 22.0
    acestep_checkpoint_dir: str = "/opt/acestep"
    audio_output_dir: str = "/app/data/audio/worker_output"
    acestep_log_dir: str = "/opt/acestep/logs"
    acestep_inner_port: int = 8101
    control_plane_url: str | None = None
    gpu_id: int | None = None
    hf_token: SecretStr | None = None
    log_level: str = "INFO"

    # Subprocess timeouts
    acestep_startup_timeout_seconds: int = 300
    acestep_shutdown_grace_seconds: int = 15
    acestep_shutdown_kill_seconds: int = 5
    acestep_health_poll_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide ``Settings`` singleton.

    First call constructs from env + .server.env. Subsequent calls
    return the cached instance. Tests should call
    ``get_settings.cache_clear()`` between cases when they manipulate
    the environment.
    """
    return Settings()


@lru_cache
def get_worker_settings() -> WorkerSettings:
    """Return the process-wide ``WorkerSettings`` singleton (acestep-worker only)."""
    return WorkerSettings()
