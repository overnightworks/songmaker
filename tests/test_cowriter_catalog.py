"""Live model catalogs for Claude, Grok, and Codex."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from songmaker_cli.cowriter.catalog import list_provider_models
from songmaker_cli.cowriter.errors import ProviderUnavailableError


def _models_payload(*ids: str) -> dict:
    return {"data": [{"id": model_id} for model_id in ids]}


def test_grok_catalog_uses_live_xai_ids(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _models_payload(
        "grok-4.6", "grok-4.5", "grok-imagine-image",
    )
    monkeypatch.setattr("songmaker_cli.cowriter.catalog.httpx.get", lambda *a, **k: response)

    assert list_provider_models("grok") == ["grok-4.5", "grok-4.6"]


def test_claude_catalog_uses_live_anthropic_ids(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _models_payload(
        "claude-opus-4-6", "claude-sonnet-4-6",
    )
    monkeypatch.setattr("songmaker_cli.cowriter.catalog.httpx.get", lambda *a, **k: response)

    assert list_provider_models("claude") == ["claude-opus-4-6", "claude-sonnet-4-6"]


def test_codex_catalog_uses_live_openai_ids(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "oa-test")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _models_payload(
        "gpt-5.4", "whisper-1", "gpt-4o", "gpt-image-1", "gpt-4o-search-preview",
    )
    monkeypatch.setattr("songmaker_cli.cowriter.catalog.httpx.get", lambda *a, **k: response)

    assert list_provider_models("codex") == ["gpt-4o", "gpt-5.4"]


def test_failed_catalog_fetch_is_named_error(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()

    def _boom(*_a, **_k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("songmaker_cli.cowriter.catalog.httpx.get", _boom)
    with pytest.raises(ProviderUnavailableError, match="grok"):
        list_provider_models("grok")


def test_invalid_catalog_json_is_named_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "oa-test")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()

    response = MagicMock()
    response.status_code = 200
    response.json.side_effect = ValueError("bad json")
    monkeypatch.setattr("songmaker_cli.cowriter.catalog.httpx.get", lambda *a, **k: response)

    with pytest.raises(ProviderUnavailableError, match="codex"):
        list_provider_models("codex")


@pytest.mark.parametrize(
    ("provider", "environment_key"),
    [("claude", "ANTHROPIC_API_KEY"), ("codex", "OPENAI_API_KEY")],
)
def test_catalog_without_api_credentials_is_named_error(
    monkeypatch, provider, environment_key,
):
    monkeypatch.delenv(environment_key, raising=False)
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()

    with pytest.raises(ProviderUnavailableError, match=provider):
        list_provider_models(provider)
