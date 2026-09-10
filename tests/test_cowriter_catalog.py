"""Route-keyed co-writer readiness and model catalogues."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from agent_providers.catalog import (
    ProviderRoute,
    ProviderRouteCapability,
    ProviderRouteReadinessState,
    list_provider_models,
    models_with_active_model,
)
from agent_providers.errors import (
    ProviderModelCatalogUnavailableError,
    SafeRouteReasonCode,
)
from agent_providers.process import AgentCliUnavailableError
from conftest import override_provider_runtime

from songmaker_cli.provider_status import (
    refresh_provider_snapshot,
)


def _models_payload(*model_ids: str) -> dict:
    return {"data": [{"id": model_id} for model_id in model_ids]}


def test_api_catalog_uses_only_the_explicit_provider_endpoint(monkeypatch):
    override_provider_runtime(xai_api_key="test-key")
    response = MagicMock(status_code=200)
    response.json.return_value = _models_payload("grok-4.6", "grok-imagine-image")
    monkeypatch.setattr(
        "agent_providers.catalog.httpx.get",
        lambda *_args, **_kwargs: response,
    )

    assert list_provider_models("grok", ProviderRoute.API) == ["grok-4.6"]


def test_cli_catalog_uses_the_explicit_cli_aliases(monkeypatch):
    monkeypatch.setattr(
        "agent_providers.catalog.list_cli_model_aliases",
        lambda: ("sonnet", "opus"),
    )

    assert list_provider_models("claude", ProviderRoute.CLI) == ["opus", "sonnet"]


def test_codex_cli_catalog_lists_visible_models_from_the_cli_catalog(monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "codex-debug-models.json"
    monkeypatch.setattr(
        "agent_providers.catalog.codex_cli_model_catalog",
        fixture.read_text,
    )

    assert list_provider_models("codex", ProviderRoute.CLI) == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.5",
        "gpt-5.4-mini",
        "gpt-5.3-codex-spark",
    ]


def test_codex_cli_catalog_sorts_same_priority_models_by_slug(monkeypatch):
    monkeypatch.setattr(
        "agent_providers.catalog.codex_cli_model_catalog",
        lambda: json.dumps({
            "models": [
                {"slug": "gpt-z", "visibility": "list", "priority": 1},
                {"slug": "gpt-a", "visibility": "list", "priority": 1},
            ],
        }),
    )

    assert list_provider_models("codex", ProviderRoute.CLI) == ["gpt-a", "gpt-z"]


def test_codex_cli_catalog_rejects_an_unreachable_cli(monkeypatch):
    def unavailable() -> str:
        raise AgentCliUnavailableError("catalog command failed")

    monkeypatch.setattr(
        "agent_providers.catalog.codex_cli_model_catalog",
        unavailable,
    )

    with pytest.raises(ProviderModelCatalogUnavailableError) as raised:
        list_provider_models("codex", ProviderRoute.CLI)

    assert raised.value.reason.code is SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR


@pytest.mark.parametrize(
    "payload",
    (
        "not-json",
        json.dumps({"models": [{"slug": "gpt-5.6", "visibility": "list", "priority": "1"}]}),
        json.dumps({"models": [{"slug": "gpt-5.6", "visibility": "hide", "priority": 1}]}),
    ),
)
def test_codex_cli_catalog_rejects_an_invalid_catalog(monkeypatch, payload):
    monkeypatch.setattr(
        "agent_providers.catalog.codex_cli_model_catalog",
        lambda: payload,
    )

    with pytest.raises(ProviderModelCatalogUnavailableError) as raised:
        list_provider_models("codex", ProviderRoute.CLI)

    assert raised.value.reason.code is SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR


def test_claude_api_catalog_remains_available_for_the_judge_api_route(monkeypatch):
    override_provider_runtime(anthropic_api_key="test-key")
    response = MagicMock(status_code=200)
    response.json.return_value = _models_payload("claude-sonnet-4-6")
    monkeypatch.setattr(
        "agent_providers.catalog.httpx.get",
        lambda *_args, **_kwargs: response,
    )

    monkeypatch.setattr("agent_providers.catalog._anthropic_sdk_available", lambda: True)
    monkeypatch.setattr("agent_providers.catalog._cli_is_logged_in", lambda _provider: False)
    snapshot = refresh_provider_snapshot("claude")

    assert snapshot.routes[ProviderRoute.API].models == ("claude-sonnet-4-6",)
    assert snapshot.routes[ProviderRoute.API].readiness is ProviderRouteReadinessState.READY
    assert (
        snapshot.routes[ProviderRoute.CLI].readiness is ProviderRouteReadinessState.NOT_CONFIGURED
    )


def test_claude_api_route_requires_the_anthropic_sdk_even_with_a_key_and_catalog(monkeypatch):
    override_provider_runtime(anthropic_api_key="test-key")
    monkeypatch.setattr("agent_providers.catalog._anthropic_sdk_available", lambda: False)
    monkeypatch.setattr("agent_providers.catalog._cli_setup_method", lambda _provider: None)
    monkeypatch.setattr(
        "agent_providers.catalog.list_provider_models",
        lambda _provider, route: ["sonnet"] if route is ProviderRoute.CLI else (
            _ for _ in ()
        ).throw(AssertionError("catalogue must not run")),
    )

    snapshot = refresh_provider_snapshot("claude")
    route = snapshot.routes[ProviderRoute.API]

    assert route.readiness is ProviderRouteReadinessState.DISTURBED
    assert route.reason is not None
    assert route.reason.code is SafeRouteReasonCode.API_HTTP_ERROR


def test_api_catalog_distinguishes_http_and_protocol_failures(monkeypatch):
    override_provider_runtime(xai_api_key="test-key")

    def unavailable(*_args, **_kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("agent_providers.catalog.httpx.get", unavailable)
    try:
        list_provider_models("grok", ProviderRoute.API)
    except ProviderModelCatalogUnavailableError as error:
        assert error.reason.code is SafeRouteReasonCode.CATALOGUE_HTTP_ERROR
    else:  # pragma: no cover - the assertion above must receive the failure
        raise AssertionError("expected the unavailable model catalogue")

    malformed = MagicMock(status_code=200)
    malformed.json.return_value = {"unexpected": []}
    monkeypatch.setattr(
        "agent_providers.catalog.httpx.get",
        lambda *_args, **_kwargs: malformed,
    )
    try:
        list_provider_models("grok", ProviderRoute.API)
    except ProviderModelCatalogUnavailableError as error:
        assert error.reason.code is SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR
    else:  # pragma: no cover - the assertion above must receive the failure
        raise AssertionError("expected the malformed model catalogue")


def test_snapshot_refreshes_both_routes(monkeypatch):
    override_provider_runtime(xai_api_key="test-key")
    monkeypatch.setattr("agent_providers.catalog._cli_is_logged_in", lambda _provider: True)
    monkeypatch.setattr(
        "agent_providers.catalog.list_provider_models",
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
    from agent_providers.process import AgentCliUnavailableError

    def failing_login(provider: str) -> bool:
        if provider == "grok":
            raise AgentCliUnavailableError("broken credentials")
        return True

    monkeypatch.setattr("agent_providers.catalog._cli_is_logged_in", failing_login)
    monkeypatch.setattr(
        "agent_providers.catalog.list_provider_models",
        lambda provider, route: [f"{provider}-{route.value}"],
    )

    grok = refresh_provider_snapshot("grok")
    codex = refresh_provider_snapshot("codex")

    assert grok.routes[ProviderRoute.CLI].readiness is ProviderRouteReadinessState.DISTURBED
    assert codex.routes[ProviderRoute.CLI].readiness is ProviderRouteReadinessState.READY


def test_retained_alias_is_appended_once_without_a_provider_prefix():
    assert models_with_active_model(["opus"], "sonnet") == ["opus", "sonnet"]
    assert models_with_active_model(["sonnet"], "sonnet") == ["sonnet"]
