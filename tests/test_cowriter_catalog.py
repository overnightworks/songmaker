"""Route-keyed co-writer readiness and model catalogues."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from songmaker_cli.cowriter.catalog import (
    DependencyUnavailableProvider,
    ProviderRoute,
    ProviderRouteCapability,
    ProviderRouteReadinessState,
    ProviderSurface,
    get_provider_configuration,
    list_provider_models,
    models_with_active_model,
    refresh_provider_snapshot,
)
from songmaker_cli.cowriter.errors import (
    ProviderModelCatalogUnavailableError,
    SafeRouteReasonCode,
)


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


def test_codex_cli_catalog_defaults_to_terra_without_removing_gpt_5_6():
    assert list_provider_models("codex", ProviderRoute.CLI) == [
        "gpt-5.6-terra",
        "gpt-5.6",
        "gpt-5.6-sol",
        "gpt-5.6-luna",
        "gpt-6-astra",
    ]


def test_claude_api_catalog_remains_available_to_the_api_only_judge(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    response = MagicMock(status_code=200)
    response.json.return_value = _models_payload("claude-sonnet-4-6")
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.httpx.get",
        lambda *_args, **_kwargs: response,
    )

    assert list_provider_models("claude", ProviderRoute.API) == ["claude-sonnet-4-6"]


def test_claude_api_route_requires_the_anthropic_sdk_even_with_a_key_and_catalog(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("songmaker_cli.cowriter.catalog._anthropic_sdk_available", lambda: False)
    monkeypatch.setattr("songmaker_cli.cowriter.catalog._cli_setup_method", lambda _provider: None)
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.list_provider_models",
        lambda _provider, route: ["sonnet"] if route is ProviderRoute.CLI else (
            _ for _ in ()
        ).throw(AssertionError("catalogue must not run")),
    )

    snapshot = refresh_provider_snapshot("claude")
    route = snapshot.routes[ProviderRoute.API]
    configuration = get_provider_configuration("claude", ProviderSurface.CO_WRITER)

    assert route.readiness is ProviderRouteReadinessState.DISTURBED
    assert route.reason is not None
    assert route.reason.code is SafeRouteReasonCode.API_HTTP_ERROR
    assert configuration == DependencyUnavailableProvider("claude", "anthropic")


def test_api_catalog_distinguishes_http_and_protocol_failures(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")

    def unavailable(*_args, **_kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("songmaker_cli.cowriter.catalog.httpx.get", unavailable)
    try:
        list_provider_models("grok", ProviderRoute.API)
    except ProviderModelCatalogUnavailableError as error:
        assert error.reason.code is SafeRouteReasonCode.CATALOGUE_HTTP_ERROR
    else:  # pragma: no cover - the assertion above must receive the failure
        raise AssertionError("expected the unavailable model catalogue")

    malformed = MagicMock(status_code=200)
    malformed.json.return_value = {"unexpected": []}
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.httpx.get",
        lambda *_args, **_kwargs: malformed,
    )
    try:
        list_provider_models("grok", ProviderRoute.API)
    except ProviderModelCatalogUnavailableError as error:
        assert error.reason.code is SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR
    else:  # pragma: no cover - the assertion above must receive the failure
        raise AssertionError("expected the malformed model catalogue")


def test_snapshot_refreshes_both_routes(monkeypatch):
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
    assert snapshot.routes[ProviderRoute.CLI].capability is ProviderRouteCapability.TOOLS_AVAILABLE
    assert snapshot.routes[ProviderRoute.CLI].reason is None
    assert snapshot.routes[ProviderRoute.API].capability is ProviderRouteCapability.TOOLS_AVAILABLE


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
    assert models_with_active_model(["opus"], "sonnet") == ["opus", "sonnet"]
    assert models_with_active_model(["sonnet"], "sonnet") == ["sonnet"]
