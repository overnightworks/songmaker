"""Settings for a worker built in a test, with placeholder connection values."""

from __future__ import annotations

from songmaker_cli.settings import Settings


def worker_settings() -> Settings:
    return Settings(
        database_url="postgresql://example",
        redis_url="redis://example",
        session_secret="session-secret",
        songmaker_internal_token="internal-token",
    )
