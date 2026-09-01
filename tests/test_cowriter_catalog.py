"""Live model catalogs for Claude, Grok, and Codex."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from songmaker_cli.claude.provider import CliLoginStatus
from songmaker_cli.claude.provider import UnavailableError as ClaudeCliUnavailableError
from songmaker_cli.cowriter.catalog import (
    ConfiguredProvider,
    ProviderSetupMethod,
    UnconfiguredProvider,
    get_provider_configuration,
    list_provider_models,
)
from songmaker_cli.cowriter.errors import (
    ProviderModelCatalogUnavailableError,
    ProviderUnavailableError,
)


def _models_payload(*ids: str) -> dict:
    return {"data": [{"id": model_id} for model_id in ids]}


def test_grok_catalog_uses_live_xai_ids(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _models_payload(
        "grok-4.6", "grok-4.5", "grok-imagine-image",
    )
    monkeypatch.setattr("songmaker_cli.cowriter.catalog.httpx.get", lambda *a, **k: response)

    assert list_provider_models("grok") == ["grok-4.5", "grok-4.6"]


def test_claude_catalog_uses_live_anthropic_ids(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _models_payload(
        "claude-opus-4-6", "claude-sonnet-4-6",
    )
    monkeypatch.setattr("songmaker_cli.cowriter.catalog.httpx.get", lambda *a, **k: response)

    assert list_provider_models("claude") == ["claude-opus-4-6", "claude-sonnet-4-6"]


def test_codex_catalog_uses_live_openai_ids(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "oa-test")

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _models_payload(
        "gpt-5.4", "whisper-1", "gpt-4o", "gpt-image-1", "gpt-4o-search-preview",
    )
    monkeypatch.setattr("songmaker_cli.cowriter.catalog.httpx.get", lambda *a, **k: response)

    assert list_provider_models("codex") == ["gpt-4o", "gpt-5.4"]


def test_failed_catalog_fetch_is_named_error(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")

    def _boom(*_a, **_k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("songmaker_cli.cowriter.catalog.httpx.get", _boom)
    with pytest.raises(
        ProviderModelCatalogUnavailableError, match="grok",
    ) as raised:
        list_provider_models("grok")
    assert type(raised.value) is ProviderModelCatalogUnavailableError


def test_invalid_catalog_json_is_named_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "oa-test")

    response = MagicMock()
    response.status_code = 200
    response.json.side_effect = ValueError("bad json")
    monkeypatch.setattr("songmaker_cli.cowriter.catalog.httpx.get", lambda *a, **k: response)

    with pytest.raises(
        ProviderModelCatalogUnavailableError, match="codex",
    ) as raised:
        list_provider_models("codex")
    assert type(raised.value) is ProviderModelCatalogUnavailableError


def test_api_key_marks_provider_as_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")

    assert get_provider_configuration("claude") == ConfiguredProvider(
        "claude", ProviderSetupMethod.API_KEY,
    )


def test_claude_cli_login_marks_provider_as_configured(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.cli_login_status",
        lambda: CliLoginStatus(logged_in=True, auth_method="claude.ai"),
    )

    assert get_provider_configuration("claude") == ConfiguredProvider(
        "claude", ProviderSetupMethod.CLAUDE_CLI,
    )


def test_claude_cli_not_logged_in_is_unconfigured(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.cli_login_status",
        lambda: CliLoginStatus(logged_in=False, auth_method=None),
    )

    assert get_provider_configuration("claude") == UnconfiguredProvider(
        "claude", "ANTHROPIC_API_KEY",
    )


@pytest.mark.parametrize(
    ("provider", "environment_key"),
    [
        ("grok", "XAI_API_KEY"),
        ("codex", "OPENAI_API_KEY"),
    ],
)
def test_unconfigured_provider_names_missing_environment_key(
    monkeypatch, provider, environment_key,
):
    monkeypatch.delenv(environment_key, raising=False)

    assert get_provider_configuration(provider) == UnconfiguredProvider(
        provider, environment_key,
    )


def test_claude_cli_catalog_uses_cli_model_aliases(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.cli_login_status",
        lambda: CliLoginStatus(logged_in=True, auth_method="claude.ai"),
    )
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.list_cli_model_aliases",
        lambda: ["sonnet", "opus", "haiku"],
    )

    assert list_provider_models("claude") == ["haiku", "opus", "sonnet"]


def test_claude_cli_catalog_failure_is_named_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.cli_login_status",
        lambda: CliLoginStatus(logged_in=True, auth_method="claude.ai"),
    )

    def _boom():
        raise ClaudeCliUnavailableError(
            "Claude CLI /model output did not contain a parseable model list",
        )

    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.list_cli_model_aliases", _boom,
    )

    with pytest.raises(
        ProviderModelCatalogUnavailableError, match="claude CLI",
    ) as raised:
        list_provider_models("claude")
    assert type(raised.value) is ProviderModelCatalogUnavailableError
    assert raised.value.provider == "claude"


def test_catalog_without_api_credentials_names_missing_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ProviderUnavailableError, match="OPENAI_API_KEY"):
        list_provider_models("codex")
