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


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("LORA_TRAINING_POLL_INTERVAL_SECONDS", "300"),
        ("LORA_TRAINING_JOB_TIMEOUT", "300"),
    ],
)
def test_rejects_an_invalid_lora_training_timeout_order(
    monkeypatch: pytest.MonkeyPatch, setting: str, value: str,
) -> None:
    monkeypatch.setenv(setting, value)

    with pytest.raises(ValidationError, match="progress poll < reaper < arq"):
        Settings(**_required_settings())


def test_voice_capacity_defaults_are_configured() -> None:
    settings = Settings(**_required_settings())

    assert settings.max_user_loras == 10
    assert settings.max_queued_lora_training_jobs == 2


@pytest.mark.parametrize(
    "setting",
    ["max_user_loras", "max_queued_lora_training_jobs"],
)
def test_rejects_non_positive_voice_capacity(setting: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**_required_settings(), **{setting: 0})
