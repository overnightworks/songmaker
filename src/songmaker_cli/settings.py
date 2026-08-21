"""Typed application settings — single source of truth for env config.

Reads ``.env`` (project root) automatically via pydantic-settings.
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

from songmaker_cli.constants import (
    AUDIO_UPLOAD_BODY_MAX_BYTES,
    JSON_REQUEST_BODY_MAX_BYTES,
    REIMPORT_BODY_MAX_BYTES,
)


def _find_env_file() -> Path | None:
    """Walk up from CWD to find .env at the project root.

    Honors ``SONGMAKER_SKIP_ENV_FILE`` (any value) to bypass loading
    entirely — used by the test suite so .env values do not leak into
    monkeypatched env tests.
    """
    import os as _os
    if "SONGMAKER_SKIP_ENV_FILE" in _os.environ:
        return None
    cwd = Path.cwd().resolve()
    for parent in (cwd, *cwd.parents):
        candidate = parent / ".env"
        if candidate.exists():
            return candidate
        if (parent / "pyproject.toml").exists():
            return None
    return None


class Settings(BaseSettings):
    """Validated application settings, loaded from env + .env.

    All env reads in ``src/songmaker_cli`` and ``src/acestep_worker`` go
    through this class. Required fields raise at startup if missing.
    Optional fields have explicit, named defaults that are visible in
    code review (no fallback chains, no sentinel coercion).
    """

    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        extra="forbid",
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
    max_request_body_bytes: int = Field(default=JSON_REQUEST_BODY_MAX_BYTES)
    max_upload_body_bytes: int = Field(default=AUDIO_UPLOAD_BODY_MAX_BYTES)
    max_reimport_body_bytes: int = Field(default=REIMPORT_BODY_MAX_BYTES)

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
    max_concurrent_sessions_per_user: int = Field(
        default=10, alias="MAX_CONCURRENT_SESSIONS_PER_USER", ge=1,
    )

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
    arq_job_timeout: int = 1000
    arq_drain_timeout: int = 300
    music_max_jobs: int = 2
    scoring_max_jobs: int = 1
    scoring_device: str = "cpu"
    stale_job_threshold_seconds: int = 1100

    # ── Soft delete ───────────────────────────────────────────────────
    soft_delete_retention_days: int = 30

    # ── Generation retention ──────────────────────────────────────────
    # Generations that are neither picked nor kept are auto-archived
    # after `generation_retention_days` and hard-deleted (files + row)
    # after `generation_hard_delete_days` additional days archived.
    generation_retention_days: int = Field(
        default=7, alias="GENERATION_RETENTION_DAYS",
    )
    generation_hard_delete_days: int = Field(
        default=30, alias="GENERATION_HARD_DELETE_DAYS",
    )

    # ── Claude ────────────────────────────────────────────────────────
    claude_chat_model: str = "claude-opus-4-6"
    claude_scoring_model: str = "claude-opus-4-6"
    anthropic_api_key: SecretStr | None = None
    xai_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    # ── MCP server (songmaker tools exposed to Claude) ────────────────
    # Only set in the subprocess spawned by chat_api when the CLI
    # launches the MCP server via --mcp-config. Identifies the acting
    # user so tool calls can run the same ownership checks as HTTP.
    songmaker_mcp_user_id: str | None = None

    # ── Admin auto-setup ──────────────────────────────────────────────
    admin_username: str | None = None
    admin_password: SecretStr | None = None

    # ── Filesystem roots (override via env for Docker volume mounts) ──
    audio_dir: str = "data/audio"
    data_dir: str = "data"

    # ── Docker Compose substitution fields ────────────────────────────
    # These live in .env so docker-compose can substitute them into
    # container environment blocks (POSTGRES_USER → the postgres
    # container, HF_TOKEN → scripts/download_models.sh, etc.). The app
    # code does not read them. Declared here so extra="forbid" still
    # recognizes them and a typo on a real app field still raises
    # ValidationError.
    postgres_user: str | None = None
    postgres_password: SecretStr | None = None
    postgres_db: str | None = None
    grafana_user: str | None = None
    grafana_password: SecretStr | None = None
    hf_token: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide ``Settings`` singleton.

    First call constructs from env + .env. Subsequent calls return the
    cached instance. Tests should call ``get_settings.cache_clear()``
    between cases when they manipulate the environment.
    """
    return Settings()


# WorkerSettings was moved to src/acestep_worker/settings.py on 2026-04-09
# because the acestep-worker container does not install songmaker_cli.
# Importing it here crashed the worker at startup with
# ``ModuleNotFoundError: No module named 'songmaker_cli'``. The class is
# now owned by acestep_worker. Any test or helper that needs it should
# ``from acestep_worker.settings import WorkerSettings, get_worker_settings``.
