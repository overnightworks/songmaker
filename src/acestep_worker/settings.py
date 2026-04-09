"""Settings for the acestep-worker container.

Lives in ``acestep_worker/`` (not ``songmaker_cli/``) because the
acestep-worker container is a slim image that does NOT install
``songmaker_cli`` — it only ships ``acestep_worker`` and
``acestep_engine``. Importing from ``songmaker_cli.settings`` here
would (and did, until 2026-04-09) crash the worker container at
startup with ``ModuleNotFoundError: No module named 'songmaker_cli'``.

Independent from ``songmaker_cli.settings.Settings`` because the GPU
worker pod has no database, no sessions, and no internal API of its
own — it only needs Redis, its own identity, and subprocess knobs.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    """Validated settings for the acestep-worker container."""

    model_config = SettingsConfigDict(
        extra="forbid",
        case_sensitive=False,
    )

    worker_id: str
    redis_url: str
    songmaker_internal_token: SecretStr | None = None
    worker_host: str | None = None
    worker_port: int = 8001
    vram_budget_gb: float = 24.0
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
def get_worker_settings() -> WorkerSettings:
    """Return the process-wide ``WorkerSettings`` singleton (acestep-worker only)."""
    return WorkerSettings()
