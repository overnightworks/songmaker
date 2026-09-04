"""Route-keyed co-writer readiness and model catalogues."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from songmaker_cli.cowriter.catalog import (
    ProviderRoute,
    ProviderRouteReadinessState,
    list_provider_models,
    models_with_active_model,
    refresh_provider_snapshot,
)
from songmaker_cli.cowriter.errors import ProviderUnavailableError, SafeRouteReasonCode


def _models_payload(*model_ids: str) -> dict:
    return {"data": [{"id": model_id} for model_id in model_ids]}


def test_api_catalog_uses_only_the_explicit_provider_endpoint(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    response = MagicMock(status_code=200)
    response.json.return_value = _models_payload("grok-4.6", "grok-imagine-image")
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.httpx.get",
        lambda *_args, **_kwargs: response,
    )

    assert list_provider_models("grok", ProviderRoute.API) == ["grok-4.6"]


def test_cli_catalog_uses_the_explicit_cli_aliases(monkeypatch):
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.list_cli_model_aliases",
        lambda: ("sonnet", "opus"),
    )

    assert list_provider_models("claude", ProviderRoute.CLI) == ["opus", "sonnet"]


def test_claude_api_catalog_is_unavailable_until_the_tool_loop_exists():
    with pytest.raises(ProviderUnavailableError) as raised:
        list_provider_models("claude", ProviderRoute.API)

    assert raised.value.reason.code is SafeRouteReasonCode.CLAUDE_API_TOOL_LOOP_PENDING


def test_snapshot_refreshes_both_routes_and_keeps_the_claude_api_pending(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setattr("songmaker_cli.cowriter.catalog._cli_is_logged_in", lambda _provider: True)
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.list_provider_models",
        lambda provider, route: [f"{provider}-{route.value}"],
    )

    snapshot = refresh_provider_snapshot("grok")

    assert set(snapshot.routes) == {ProviderRoute.CLI, ProviderRoute.API}
    assert all(
        item.readiness is ProviderRouteReadinessState.READY
        for item in snapshot.routes.values()
    )


def test_cli_probe_failure_is_isolated_to_its_provider_route(monkeypatch):
    from songmaker_cli.agent_cli import AgentCliUnavailableError

    def failing_login(provider: str) -> bool:
        if provider == "grok":
            raise AgentCliUnavailableError("broken credentials")
        return True

    monkeypatch.setattr("songmaker_cli.cowriter.catalog._cli_is_logged_in", failing_login)
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.list_provider_models",
        lambda provider, route: [f"{provider}-{route.value}"],
    )

    grok = refresh_provider_snapshot("grok")
    codex = refresh_provider_snapshot("codex")

    assert grok.routes[ProviderRoute.CLI].readiness is ProviderRouteReadinessState.DISTURBED
    assert codex.routes[ProviderRoute.CLI].readiness is ProviderRouteReadinessState.READY


def test_retained_alias_is_appended_once_without_a_provider_prefix():
    assert models_with_active_model("claude", ["opus"], "sonnet") == ["opus", "sonnet"]
    assert models_with_active_model("claude", ["sonnet"], "sonnet") == ["sonnet"]
