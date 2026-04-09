"""Engine-package settings — kept independent of songmaker_cli.

The engine package must not import from songmaker_cli (one-way
dependency rule). It owns its own minimal settings module so the
ACE-Step HTTP client can read its own env vars without violating
the boundary.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class EngineSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".server.env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    acestep_host: str = "http://localhost"
    acestep_port: int = 8001
    acestep_poll_timeout: float = 600.0


@lru_cache
def get_engine_settings() -> EngineSettings:
    return EngineSettings()
