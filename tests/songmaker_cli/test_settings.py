"""Tests for application settings validation."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from support.web_app import make_test_app, seed_session, seed_user

from songmaker_cli.api_models.songs import generation_expiry
from songmaker_cli.db.database_url import (
    POSTGRESQL_PSYCOPG2_DRIVERNAME,
    connection_url_from_settings,
)
from songmaker_cli.settings import (
    UNKNOWN_COMMIT,
    UNRELEASED_TAG,
    Settings,
    get_settings,
)

_REMOVED_COVER_KEYS = ("COVER_EXECUTOR", "COVER_JOB_BUDGET_SECONDS", "COVER_CLI_DEADLINE_SECONDS")
_RETIRED_KEYS = (
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "OPENAI_API_KEY",
    "CLAUDE_CHAT_MODEL",
    "CODEX_CLI_MAX_CONCURRENT_PROCESSES",
    "COVER_MAX_CONCURRENT_RUNS",
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


@pytest.mark.parametrize("key", _RETIRED_KEYS)
def test_a_dotenv_that_still_sets_a_retired_key_builds_settings(
    tmp_path: Path, key: str,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{key}=1\n")

    Settings(_env_file=env_file, **_required_settings())


def test_settings_build_with_none_of_the_removed_cover_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in _REMOVED_COVER_KEYS:
        monkeypatch.delenv(key, raising=False)

    Settings(**_required_settings())


@pytest.mark.parametrize("key", _REMOVED_COVER_KEYS)
def test_a_dotenv_with_a_removed_cover_key_raises(tmp_path: Path, key: str) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{key}=1\n")
    required = _required_settings()

    with pytest.raises(ValidationError):
        Settings(_env_file=env_file, **required)


@pytest.mark.parametrize(
    "setting",
    ["max_user_loras", "max_queued_lora_training_jobs"],
)
def test_rejects_non_positive_voice_capacity(setting: str) -> None:
    required = _required_settings()
    with pytest.raises(ValidationError):
        Settings(**required, **{setting: 0})


@pytest.mark.parametrize(("configured", "expected_days"), [(None, 30), ("7", 7)])
def test_final_deletion_days_sets_the_archived_take_expiry(
    monkeypatch: pytest.MonkeyPatch, fresh_settings, configured: str | None, expected_days: int,
) -> None:
    monkeypatch.delenv("FINAL_DELETION_DAYS", raising=False)
    if configured is not None:
        monkeypatch.setenv("FINAL_DELETION_DAYS", configured)
    now = datetime.now(timezone.utc)
    archived = SimpleNamespace(
        is_picked=False, is_kept=False, is_archived=True, archived_at=now, created_at=now,
    )

    assert get_settings().final_deletion_days == expected_days
    assert generation_expiry(archived) == now + timedelta(days=expected_days)
    assert get_settings().generation_retention_days == 7


@pytest.mark.parametrize(("configured", "expected_days"), [(None, 30), ("7", 7)])
def test_retention_preview_reports_the_final_deletion_setting(
    tmp_path, pg_factory, monkeypatch: pytest.MonkeyPatch, fresh_settings,
    configured: str | None, expected_days: int,
) -> None:
    monkeypatch.delenv("FINAL_DELETION_DAYS", raising=False)
    if configured is not None:
        monkeypatch.setenv("FINAL_DELETION_DAYS", configured)
    client, _ = make_test_app(tmp_path, factory=pg_factory)
    with client.app.state.ctx.db() as session:
        seed_user(session, "admin", "admin")
        session.commit()
    seed_session(client, "admin")

    response = client.get("/api/admin/generation-retention/preview")

    assert response.json()["hard_delete_days"] == expected_days


@pytest.mark.parametrize("value", ["0", "-1", "soon", "1.5"])
def test_rejects_an_invalid_final_deletion_days(
    monkeypatch: pytest.MonkeyPatch, value: str,
) -> None:
    monkeypatch.setenv("FINAL_DELETION_DAYS", value)
    required = _required_settings()

    with pytest.raises(ValidationError, match="final_deletion_days|FINAL_DELETION_DAYS"):
        Settings(**required)


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
    required = _required_settings()

    with pytest.raises(ValidationError, match="TOKEN_CLIENTS has an empty entry"):
        Settings(**required, token_clients=malformed)


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


@pytest.mark.parametrize(
    ("given", "origin"),
    [
        ("", ""),
        ("  ", ""),
        ("https://songmaker.example", "https://songmaker.example"),
        (" https://songmaker.example \n", "https://songmaker.example"),
        ("https://songmaker.example/", "https://songmaker.example"),
        ("https://songmaker.example?x=1#frag", "https://songmaker.example"),
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
        ("http://[::1]:8080", "http://[::1]:8080"),
    ],
)
def test_public_base_url_is_stored_as_the_bare_origin(given: str, origin: str) -> None:
    assert Settings(**_required_settings(), public_base_url=given).public_base_url == origin


@pytest.mark.parametrize(
    "malformed",
    [
        "songmaker.example",
        "ftp://songmaker.example",
        "http://https://host",
        "https://user:pass@songmaker.example",
        "https://songmaker.example/app",
    ],
)
def test_a_malformed_public_base_url_fails_loud_and_names_the_value(malformed: str) -> None:
    required = _required_settings()

    with pytest.raises(ValidationError, match="PUBLIC_BASE_URL") as refused:
        Settings(**required, public_base_url=malformed)

    assert malformed in str(refused.value)


_AGENT_ENVIRONMENT = {
    "AGENT__BACKEND": "litellm",
    "AGENT__GATEWAY__ORIGIN": "http://gateway.test:4000",
    "AGENT__GATEWAY__KEY_FILE": "/run/secrets/gateway_key",
    "AGENT__API_GROUP": "/apps/songmaker/api",
}


def _with_environment(monkeypatch: pytest.MonkeyPatch, environment: dict[str, str]) -> None:
    for name, value in environment.items():
        monkeypatch.setenv(name, value)


def test_an_unset_agent_reads_as_none() -> None:
    assert Settings(**_required_settings()).agent is None


def test_a_fully_set_agent_is_read_from_the_nested_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_environment(monkeypatch, _AGENT_ENVIRONMENT)

    agent = Settings(**_required_settings()).agent

    assert agent is not None
    assert (agent.gateway.origin, str(agent.gateway.key_file), agent.api_group) == (
        _AGENT_ENVIRONMENT["AGENT__GATEWAY__ORIGIN"],
        _AGENT_ENVIRONMENT["AGENT__GATEWAY__KEY_FILE"],
        _AGENT_ENVIRONMENT["AGENT__API_GROUP"],
    )


_MCP_ENVIRONMENT = {"AGENT__MCP_CLIENT_ID": "agents", "AGENT__MCP_SCOPE": "songmaker:mcp"}


def test_an_agent_group_without_the_mcp_client_is_unused_and_stays_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_environment(monkeypatch, {**_AGENT_ENVIRONMENT, "AGENT__MCP_AGENT_GROUP": "/agents"})

    agent = Settings(**_required_settings()).agent

    assert agent is not None
    assert (agent.mcp_client_id, agent.mcp_agent_group) == (None, "/agents")


def test_mcp_on_without_an_agent_group_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_environment(monkeypatch, {**_AGENT_ENVIRONMENT, **_MCP_ENVIRONMENT})
    required = _required_settings()

    with pytest.raises(ValidationError, match="mcp_agent_group"):
        Settings(**required)


@pytest.mark.parametrize(
    "environment",
    [
        {"AGENT__BACKEND": "litellm"},
        {**_AGENT_ENVIRONMENT, "AGENT__GATEWAY__COLOUR": "blue"},
        {name: "" for name in _AGENT_ENVIRONMENT},
        {**_AGENT_ENVIRONMENT, "AGENT__GATEWAY__CA_FILE": ""},
        {**_AGENT_ENVIRONMENT, "AGENT__GATEWAY__CA_FILE": "/run/secrets/ca.pem"},
    ],
    ids=["partly-set", "unknown-key", "all-empty", "empty-ca-file", "ca-file-for-http"],
)
def test_a_malformed_agent_value_stops_startup(
    monkeypatch: pytest.MonkeyPatch, environment: dict[str, str],
) -> None:
    _with_environment(monkeypatch, environment)
    required = _required_settings()

    with pytest.raises(ValidationError, match="agent"):
        Settings(**required)


def test_a_wrongly_delimited_agent_name_is_ignored_and_reads_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_GATEWAY__ORIGIN", "http://gateway.test:4000")

    assert Settings(**_required_settings()).agent is None


@pytest.fixture
def secrets_only_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave the secret fields to the secrets directory under test."""
    for name in ("SESSION_SECRET", "SONGMAKER_INTERNAL_TOKEN", "POSTGRES_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://app@db:5432/songs")


def _write_secret_files(directory: Path, **contents: str) -> None:
    for name, content in contents.items():
        (directory / name).write_text(content)


@pytest.mark.usefixtures("secrets_only_environment")
def test_secret_files_set_the_secret_fields(tmp_path: Path) -> None:
    _write_secret_files(
        tmp_path,
        session_secret="session-from-file\n",
        songmaker_internal_token="token-from-file",
        postgres_password="password-from-file",
    )

    settings = Settings(_secrets_dir=tmp_path)

    assert settings.session_secret.get_secret_value() == "session-from-file"
    assert settings.songmaker_internal_token.get_secret_value() == "token-from-file"
    assert settings.postgres_password.get_secret_value() == "password-from-file"


@pytest.mark.usefixtures("secrets_only_environment")
def test_files_in_the_secrets_directory_that_settings_do_not_declare_are_ignored(
    tmp_path: Path,
) -> None:
    _write_secret_files(
        tmp_path,
        session_secret="s",
        songmaker_internal_token="t",
        keycloak_client_secret="mounted-for-the-web-service",
    )

    assert Settings(_secrets_dir=tmp_path).session_secret.get_secret_value() == "s"


@pytest.mark.usefixtures("secrets_only_environment")
def test_the_environment_wins_over_a_secret_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_secret_files(tmp_path, session_secret="from-file", songmaker_internal_token="t")
    monkeypatch.setenv("SESSION_SECRET", "from-environment")

    assert Settings(_secrets_dir=tmp_path).session_secret.get_secret_value() == "from-environment"


@pytest.mark.usefixtures("secrets_only_environment")
@pytest.mark.parametrize(
    "field", ["session_secret", "songmaker_internal_token", "postgres_password"],
)
def test_an_empty_secret_file_is_refused_naming_the_field(tmp_path: Path, field: str) -> None:
    files = {"session_secret": "s", "songmaker_internal_token": "t", field: ""}
    _write_secret_files(tmp_path, **files)

    with pytest.raises(ValidationError, match=field):
        Settings(_secrets_dir=tmp_path)


def test_a_missing_required_setting_names_the_field_without_showing_a_loaded_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A short input dict is shown whole; a longer one is cut in the middle.
    for name in list(os.environ):
        monkeypatch.delenv(name)
    _write_secret_files(tmp_path, postgres_password="hunter2")

    with pytest.raises(ValidationError, match="database_url") as refusal:
        Settings(_secrets_dir=tmp_path, _env_file=None)

    assert "hunter2" not in str(refusal.value)


@pytest.mark.usefixtures("secrets_only_environment")
def test_the_connection_url_joins_the_base_and_the_password_file(tmp_path: Path) -> None:
    _write_secret_files(
        tmp_path,
        session_secret="s",
        songmaker_internal_token="t",
        postgres_password="p@ss:w/rd %",
    )

    url = connection_url_from_settings(Settings(_secrets_dir=tmp_path))

    assert (url.username, url.password, url.host, url.database) == (
        "app", "p@ss:w/rd %", "db", "songs",
    )


@pytest.mark.usefixtures("secrets_only_environment")
def test_a_password_in_the_database_url_and_in_a_file_is_refused_without_showing_either(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:inline-secret@db/songs")
    _write_secret_files(
        tmp_path,
        session_secret="s",
        songmaker_internal_token="t",
        postgres_password="file-secret",
    )
    settings = Settings(_secrets_dir=tmp_path)

    with pytest.raises(ValueError, match="DATABASE_URL") as refusal:
        connection_url_from_settings(settings)

    assert "inline-secret" not in str(refusal.value)
    assert "file-secret" not in str(refusal.value)


def test_without_a_secrets_directory_the_database_url_keeps_its_own_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    settings = Settings(
        **{**_required_settings(), "database_url": "postgresql://app:today@db:5432/songs"},
        _secrets_dir=None,
    )

    assert connection_url_from_settings(settings).render_as_string(hide_password=False) == (
        f"{POSTGRESQL_PSYCOPG2_DRIVERNAME}://app:today@db:5432/songs"
    )
