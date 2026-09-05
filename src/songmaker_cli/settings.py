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

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from acestep_engine.settings import EngineSettings
from songmaker_cli.constants import (
    AUDIO_UPLOAD_BODY_MAX_BYTES,
    CLAUDE_SCORING_MODEL_DEFAULT,
    CODEX_CLI_MAX_CONCURRENT_PROCESSES,
    COVER_CLI_DEADLINE_SECONDS,
    COVER_JOB_BUDGET_SECONDS,
    COVER_JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS,
    COVER_MAX_CONCURRENT_RUNS,
    COVER_UPLOAD_BODY_MAX_BYTES,
    JSON_REQUEST_BODY_MAX_BYTES,
    LORA_TRAINING_HEARTBEAT_STALE_THRESHOLD_SECONDS,
    REIMPORT_BODY_MAX_BYTES,
    SCORER_TIMEOUT_SECONDS,
    TEXT_ACCURACY_TIMEOUT_SECONDS,
    acestep_sse_read_timeout_seconds,
    generate_job_heartbeat_stale_threshold_seconds,
)


@dataclass(frozen=True)
class LoraTrainingJobConfig:
    """Explicit LoRA training payload owned by Songmaker settings."""

    lokr_linear_dim: int
    lokr_linear_alpha: int
    lokr_factor: int
    lokr_decompose_both: bool
    lokr_use_tucker: bool
    lokr_use_scalar: bool
    lokr_weight_decompose: bool
    learning_rate: float
    train_epochs: int
    train_batch_size: int
    gradient_accumulation: int
    save_every_n_epochs: int
    training_shift: float
    training_seed: int
    gradient_checkpointing: bool
    poll_interval_seconds: float

    def payload(self) -> dict[str, int | float | bool]:
        return {
            "lokr_linear_dim": self.lokr_linear_dim,
            "lokr_linear_alpha": self.lokr_linear_alpha,
            "lokr_factor": self.lokr_factor,
            "lokr_decompose_both": self.lokr_decompose_both,
            "lokr_use_tucker": self.lokr_use_tucker,
            "lokr_use_scalar": self.lokr_use_scalar,
            "lokr_weight_decompose": self.lokr_weight_decompose,
            "learning_rate": self.learning_rate,
            "train_epochs": self.train_epochs,
            "train_batch_size": self.train_batch_size,
            "gradient_accumulation": self.gradient_accumulation,
            "save_every_n_epochs": self.save_every_n_epochs,
            "training_shift": self.training_shift,
            "training_seed": self.training_seed,
            "gradient_checkpointing": self.gradient_checkpointing,
            "poll_interval_seconds": self.poll_interval_seconds,
        }


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

    @model_validator(mode="after")
    def validate_job_timeout_orders(self) -> Settings:
        """Keep scheduler, reaper, and arq's silent-worker bounds ordered."""
        sse_read_timeout = acestep_sse_read_timeout_seconds(
            EngineSettings().acestep_poll_timeout,
        )
        generate_reaper_threshold = generate_job_heartbeat_stale_threshold_seconds(
            sse_read_timeout,
        )
        if not sse_read_timeout < generate_reaper_threshold < self.arq_job_timeout:
            raise ValueError(
                "Generation timeout order must be SSE read < reaper < arq "
                f"({sse_read_timeout} < {generate_reaper_threshold} < "
                f"{self.arq_job_timeout})",
            )
        if not (
            self.lora_training_poll_interval_seconds
            < LORA_TRAINING_HEARTBEAT_STALE_THRESHOLD_SECONDS
            < self.lora_training_job_timeout
        ):
            raise ValueError(
                "LoRA training timeout order must be progress poll < reaper < arq "
                f"({self.lora_training_poll_interval_seconds} < "
                f"{LORA_TRAINING_HEARTBEAT_STALE_THRESHOLD_SECONDS} < "
                f"{self.lora_training_job_timeout})",
            )
        if not (
            self.cover_cli_deadline_seconds
            < COVER_JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS
            < self.cover_job_budget_seconds
        ):
            raise ValueError(
                "Cover timeout order must be CLI deadline < reaper < job budget "
                f"({self.cover_cli_deadline_seconds} < "
                f"{COVER_JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS} < "
                f"{self.cover_job_budget_seconds})",
            )
        if self.cover_max_concurrent_runs > self.codex_cli_max_concurrent_processes:
            raise ValueError("Cover process cap cannot exceed the Codex process cap")
        return self

    # ── HTTP server ───────────────────────────────────────────────────
    host: str = "127.0.0.1"
    request_timeout_seconds: int = Field(default=30, alias="REQUEST_TIMEOUT")
    allowed_hosts: str = ""
    cors_origin: str | None = None
    trusted_proxies: str = ""
    # The one owner of "what address am I reachable at from outside" for
    # share links (#339). Empty means unconfigured: share endpoints then
    # fail loudly (api_helpers.resolve_public_base_url()) instead of
    # guessing a scheme from the request.
    public_base_url: str = ""
    max_request_body_bytes: int = Field(default=JSON_REQUEST_BODY_MAX_BYTES)
    max_upload_body_bytes: int = Field(default=AUDIO_UPLOAD_BODY_MAX_BYTES)
    max_reimport_body_bytes: int = Field(default=REIMPORT_BODY_MAX_BYTES)
    max_cover_upload_body_bytes: int = Field(default=COVER_UPLOAD_BODY_MAX_BYTES)

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
    cover_suggestions_daily_limit: int = Field(default=10, ge=1)
    cover_cli_deadline_seconds: int = Field(default=COVER_CLI_DEADLINE_SECONDS, ge=1)
    cover_job_budget_seconds: int = Field(default=COVER_JOB_BUDGET_SECONDS, ge=1)
    codex_cli_max_concurrent_processes: int = Field(
        default=CODEX_CLI_MAX_CONCURRENT_PROCESSES, ge=1,
    )
    cover_max_concurrent_runs: int = Field(default=COVER_MAX_CONCURRENT_RUNS, ge=1)
    max_queue_depth: int = 100
    max_user_active_jobs: int = 10
    ip_rate_limit: int = 120
    # Range-request media (`/audio/*` and its Media-class siblings, see
    # `middleware/rate_limit.py`) is a distinct budget class from plain API
    # calls (issue #257): a single MP3 played with normal scrubbing is
    # estimated at roughly 40 range requests (order-of-magnitude from
    # typical browser Range-chunking behavior -- estimated, not measured; no
    # cheap existing e2e report captured real counts). A user comparing
    # takes can move through several songs within a minute -- 40 * 5 songs =
    # 200 requests/min in ordinary use. 600 leaves 3x headroom for
    # aggressive seeking while still bounding disk I/O per IP (not
    # unlimited).
    media_rate_limit: int = 600
    # SSE connection *opens* (issue #257), sized between the legitimate
    # worst case and the observed storm rate:
    #   legitimate worst case: a normal page load opens one resource-events
    #   stream plus one job stream per active job. At the
    #   `max_user_active_jobs` default (10) that is 11 opens/load; 3 loads
    #   within a minute (full queue, operator reloads) = 33.
    #   storm rate: the operator incident's reconnect storm ran at roughly
    #   80 opens/min. It self-terminates, but not via a backoff -- there
    #   isn't one yet (that's the still-open #257 frontend slice).
    #   `MAX_POLL_ERRORS` (`frontend/src/lib/stores/jobs.ts`) is a plain
    #   error counter with no delay, closing the EventSource after 10
    #   failures; a 429 to an EventSource is also fatal per spec (no
    #   browser auto-reconnect), so the burst is short-lived either way.
    # 45 sits clearly above 33 and clearly below 80. This has no live
    # dependency on `max_user_active_jobs` -- raising that setting should
    # prompt re-checking this comment's math, not a settings cross-reference.
    # The resource-events endpoint additionally enforces its own tighter
    # per-user open limit (`resource_event_stream_open_limit` below).
    stream_rate_limit: int = 45
    # Resource-event SSE stream opens per user per
    # `RESOURCE_EVENT_STREAM_OPEN_WINDOW_SECONDS` (constants.py) — tighter
    # than `stream_rate_limit` above because this stream also holds a leased
    # DB connection for its whole lifetime (see resource_event_api.py). CI
    # overrides this the same way it overrides `ip_rate_limit`
    # (docker-compose.ci.yml): the e2e suite reuses one seeded user across
    # every browser context, so its opens are additive against this single
    # per-user budget in a way production traffic across many real users
    # never is.
    resource_event_stream_open_limit: int = 12
    # Concurrency lease for GET /api/jobs/{id}/stream (#331 Finding 2, and
    # review rounds 2026-09-01/02 on Finding 1 below). The endpoint takes no
    # request-scoped `Depends()` at all -- not `get_db_session`, and not
    # `get_current_user` either, because that dependency itself takes
    # `Depends(get_db_session)` and a first attempt that only dropped the
    # former still pinned a pool connection through the latter for the
    # whole stream. Auth and the access check instead run as plain function
    # calls against one short-lived `ctx.db()` session that closes before
    # the lease is acquired or the StreamingResponse exists (see
    # api_stream_job, which follows resource_event_api.py's
    # api_stream_resource_events exactly); every poll does the same (see
    # _fetch_job_response). So no single job stream pins a pool connection
    # for its lifetime, and this lease is NOT a share of
    # database_pool_size/max_overflow the way the resource-event lease is;
    # it is a flat, hard concurrency cap against a runaway client (bug or
    # storm) opening far more job streams than any real page load does.
    # max_per_user mirrors max_user_active_jobs above (a user cannot
    # legitimately watch more job streams than active jobs); max_global
    # matches the already-vetted worst case in stream_rate_limit's comment
    # (one resource stream + one job stream per active job, several page
    # loads within a minute).
    job_stream_lease_max_per_user: int = 10
    job_stream_lease_max_global: int = 40

    # ── arq workers ───────────────────────────────────────────────────
    arq_job_timeout: int = 1000
    arq_drain_timeout: int = 300
    max_user_loras: int = Field(default=10, ge=1)
    max_queued_lora_training_jobs: int = Field(default=2, ge=1)
    lora_training_job_timeout: int = Field(default=3600, gt=0)
    lora_training_lokr_linear_dim: int = Field(default=64, ge=1, le=256)
    lora_training_lokr_linear_alpha: int = Field(default=128, ge=1, le=512)
    lora_training_lokr_factor: int = -1
    lora_training_lokr_decompose_both: bool = False
    lora_training_lokr_use_tucker: bool = False
    lora_training_lokr_use_scalar: bool = False
    lora_training_lokr_weight_decompose: bool = True
    lora_training_learning_rate: float = Field(default=0.03, gt=0.0)
    lora_training_epochs: int = Field(default=500, ge=1)
    lora_training_batch_size: int = Field(default=1, ge=1)
    lora_training_gradient_accumulation: int = Field(default=4, ge=1)
    lora_training_save_every_n_epochs: int = Field(default=5, ge=1)
    lora_training_training_shift: float = Field(default=3.0, ge=0.0)
    lora_training_training_seed: int = 42
    lora_training_gradient_checkpointing: bool = False
    lora_training_poll_interval_seconds: float = Field(default=5.0, gt=0.0)
    music_max_jobs: int = 2
    scoring_max_jobs: int = 1
    scoring_device: str = "cpu"
    scorer_timeout_seconds: int = SCORER_TIMEOUT_SECONDS

    text_accuracy_timeout_seconds: int = TEXT_ACCURACY_TIMEOUT_SECONDS

    @property
    def lora_training_config(self) -> LoraTrainingJobConfig:
        return LoraTrainingJobConfig(
            lokr_linear_dim=self.lora_training_lokr_linear_dim,
            lokr_linear_alpha=self.lora_training_lokr_linear_alpha,
            lokr_factor=self.lora_training_lokr_factor,
            lokr_decompose_both=self.lora_training_lokr_decompose_both,
            lokr_use_tucker=self.lora_training_lokr_use_tucker,
            lokr_use_scalar=self.lora_training_lokr_use_scalar,
            lokr_weight_decompose=self.lora_training_lokr_weight_decompose,
            learning_rate=self.lora_training_learning_rate,
            train_epochs=self.lora_training_epochs,
            train_batch_size=self.lora_training_batch_size,
            gradient_accumulation=self.lora_training_gradient_accumulation,
            save_every_n_epochs=self.lora_training_save_every_n_epochs,
            training_shift=self.lora_training_training_shift,
            training_seed=self.lora_training_training_seed,
            gradient_checkpointing=self.lora_training_gradient_checkpointing,
            poll_interval_seconds=self.lora_training_poll_interval_seconds,
        )

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
    claude_scoring_model: str = CLAUDE_SCORING_MODEL_DEFAULT
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

    # ── Alert channel (issue #333) ─────────────────────────────────────
    # Read directly from .env by scripts/alert.sh (systemd OnFailure=)
    # and by the alertmanager container's startup command (fed by
    # monitoring/rules/alert.rules.yml) — neither goes through this app
    # process. Declared here only so extra="forbid" recognizes them
    # instead of raising ValidationError the moment an operator sets
    # them up.
    alert_email_to: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None


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
