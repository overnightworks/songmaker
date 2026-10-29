"""Tests for application settings validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from songmaker_cli.constants import DEFAULT_COVER_EXECUTOR
from songmaker_cli.settings import (
    UNKNOWN_COMMIT,
    UNRELEASED_TAG,
    CoverExecutor,
    Settings,
    get_settings,
)


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
    required = _required_settings()

    with pytest.raises(ValidationError, match="SSE read < reaper < arq"):
        Settings(**required)


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
    required = _required_settings()

    with pytest.raises(ValidationError, match="progress poll < reaper < arq"):
        Settings(**required)


def test_voice_capacity_defaults_are_configured() -> None:
    settings = Settings(**_required_settings())

    assert settings.max_user_loras == 10
    assert settings.max_queued_lora_training_jobs == 2


def test_codex_process_caps_default_to_the_single_pool_contract() -> None:
    settings = Settings(**_required_settings())

    assert settings.codex_cli_max_concurrent_processes == 8
    assert settings.cover_max_concurrent_runs == 1


def test_cover_executor_defaults_to_web_and_rejects_unknown_values() -> None:
    assert DEFAULT_COVER_EXECUTOR is CoverExecutor.WEB
    settings = Settings(**_required_settings())
    assert settings.cover_executor is CoverExecutor.WEB

    required = _required_settings()
    with pytest.raises(ValidationError):
        Settings(**required, cover_executor="unknown")


def test_cover_executor_rejects_an_unknown_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COVER_EXECUTOR", "unknown")
    required = _required_settings()

    with pytest.raises(ValidationError):
        Settings(**required)


def test_rejects_a_cover_cap_above_the_codex_process_cap() -> None:
    required = _required_settings()
    with pytest.raises(ValidationError, match="Cover process cap"):
        Settings(
            **required,
            codex_cli_max_concurrent_processes=1,
            cover_max_concurrent_runs=2,
        )


@pytest.mark.parametrize(
    "setting",
    ["max_user_loras", "max_queued_lora_training_jobs"],
)
def test_rejects_non_positive_voice_capacity(setting: str) -> None:
    required = _required_settings()
    with pytest.raises(ValidationError):
        Settings(**required, **{setting: 0})


def test_default_settings_values() -> None:
    settings = get_settings()
    assert settings.session_idle_seconds == 60 * 60 * 24 * 7
    assert settings.session_absolute_max_age_seconds == 60 * 60 * 24 * 30
    assert settings.generation_rate_limit_user == 30
    assert settings.scoring_rate_limit_user == 100
    assert settings.chat_rate_limit_user == 300
    assert settings.max_queue_depth == 100
    assert settings.max_user_active_jobs == 10
    assert settings.max_concurrent_sessions_per_user == 10


def test_a_dotenv_with_the_retired_scoring_model_key_still_validates(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("CLAUDE_SCORING_MODEL=claude-opus-4-6\n")

    Settings(_env_file=env_file, **_required_settings())


def test_a_dotenv_with_a_misspelt_key_still_raises(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("CLAUDE_SCORING_MODLE=claude-opus-4-6\n")
    required_settings = _required_settings()

    with pytest.raises(ValidationError):
        Settings(_env_file=env_file, **required_settings)


@pytest.mark.parametrize(
    ("release", "commit", "expected_release", "expected_commit"),
    [
        (None, None, UNRELEASED_TAG, UNKNOWN_COMMIT),
        ("v2026.10.28.4", "a" * 40, "v2026.10.28.4", "a" * 40),
        ("", "", UNRELEASED_TAG, UNKNOWN_COMMIT),
        ("  ", "  ", UNRELEASED_TAG, UNKNOWN_COMMIT),
    ],
    ids=["unset", "set", "empty", "blank"],
)
def test_release_settings_resolve_missing_values_to_named_constants(
    monkeypatch: pytest.MonkeyPatch,
    release: str | None, commit: str | None, expected_release: str, expected_commit: str,
) -> None:
    for name, value in (("SONGMAKER_RELEASE", release), ("SONGMAKER_COMMIT", commit)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)

    settings = Settings(**_required_settings())

    assert settings.songmaker_release == expected_release
    assert settings.songmaker_commit == expected_commit


@pytest.mark.parametrize("malformed", ["hal,", ",hal", "hal,,other", " "])
def test_token_clients_with_an_empty_entry_fail_loud(malformed: str) -> None:
    with pytest.raises(ValidationError, match="TOKEN_CLIENTS has an empty entry"):
        Settings(**_required_settings(), token_clients=malformed)


@pytest.mark.parametrize(
    ("given", "admitted"),
    [
        ("", set()),
        ("hal", {"hal"}),
        (" hal , other", {"hal", "other"}),
        ("hal,HAL", {"hal", "HAL"}),
    ],
)
def test_token_clients_are_trimmed_and_matched_exactly(given: str, admitted: set[str]) -> None:
    assert Settings(**_required_settings(), token_clients=given).token_client_ids == admitted
