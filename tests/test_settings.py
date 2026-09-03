"""Tests for application settings validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from songmaker_cli.settings import Settings


def _required_settings() -> dict[str, str]:
    return {
        "database_url": "postgresql://example",
        "redis_url": "redis://example",
        "session_secret": "session-secret",
        "songmaker_internal_token": "internal-token",
    }


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("ACESTEP_POLL_TIMEOUT", "1200"),
        ("ARQ_JOB_TIMEOUT", "760"),
    ],
)
def test_rejects_an_invalid_generation_timeout_order(
    monkeypatch: pytest.MonkeyPatch, setting: str, value: str,
) -> None:
    monkeypatch.setenv(setting, value)

    with pytest.raises(ValidationError, match="SSE read < reaper < arq"):
        Settings(**_required_settings())
