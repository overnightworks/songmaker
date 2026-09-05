"""Co-writer model catalogs from provider APIs and CLI routes."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from importlib.util import find_spec
from typing import Final

import httpx
from pydantic import SecretStr

from songmaker_cli.agent_cli import (
    AgentCliUnavailableError,
    codex_cli_access_token_is_present,
    codex_cli_login,
    grok_cli_status,
    grok_cli_token_is_present,
)
from songmaker_cli.claude.provider import (
    CLAUDE_CLI_MODEL_CATALOG_ERROR,
    cli_login_status,
    list_cli_model_aliases,
)
from songmaker_cli.claude.provider import (
    UnavailableError as ClaudeCliUnavailableError,
)
from songmaker_cli.constants import (
    ANTHROPIC_API_VERSION,
    COWRITER_ANTHROPIC_MODELS_URL,
    COWRITER_CLAUDE_MODEL_PREFIX,
    COWRITER_GROK_MODEL_PREFIX,
    COWRITER_GROK_MODELS_URL,
    COWRITER_GROK_NON_CHAT_MARKERS,
    COWRITER_MODELS_TIMEOUT_SECONDS,
    COWRITER_OPENAI_CHAT_PREFIXES,
    COWRITER_OPENAI_MODELS_URL,
    COWRITER_OPENAI_NON_CHAT_MARKERS,
    COWRITER_PROVIDERS,
)
from songmaker_cli.cowriter.errors import (
    ProviderModelCatalogUnavailableError,
    ProviderUnavailableError,
    SafeRouteReason,
    SafeRouteReasonCode,
    normalize_route_failure,
)
from songmaker_cli.settings import Settings, get_settings

_CLAUDE_PROVIDER: Final = "claude"
_GROK_PROVIDER: Final = "grok"
_CODEX_PROVIDER: Final = "codex"
_ANTHROPIC_SDK_DISTRIBUTION: Final = "anthropic"
ANTHROPIC_API_KEY_ENVIRONMENT: Final = "ANTHROPIC_API_KEY"
XAI_API_KEY_ENVIRONMENT: Final = "XAI_API_KEY"
OPENAI_API_KEY_ENVIRONMENT: Final = "OPENAI_API_KEY"
_API_KEY_SETUP_LABEL: Final = "API key"
_CLI_LOGIN_SETUP_LABEL: Final = "CLI login"

# Owner: Codex CLI route. Checked 2026-09-04: ``codex --help`` and
# ``codex exec --help`` accept ``--model <MODEL>`` but do not enumerate models.
# Source: https://developers.openai.com/api/docs/guides/latest-model
_CODEX_CLI_KNOWN_MODELS: Final = (
    "gpt-5.6-terra",
    "gpt-5.6",
    "gpt-5.6-sol",
    "gpt-5.6-luna",
    "gpt-6-astra",
)
_CODEX_CLI_KNOWN_MODELS_SOURCE: Final = "known models for the CLI route"

log = logging.getLogger(__name__)

_provider_snapshots_lock = threading.Lock()
_provider_snapshots: dict[str, "ProviderSnapshot"] = {}


class ProviderSetupMethod(StrEnum):
    API_KEY = "api_key"
    CLAUDE_CLI = "claude_cli"
    GROK_CLI = "grok_cli"
    CODEX_CLI = "codex_cli"


class ProviderSurface(StrEnum):
    CO_WRITER = "cowriter"
    JUDGE = "judge"


class ProviderRoute(StrEnum):
    CLI = "cli"
    API = "api"


class ProviderRouteReadinessState(StrEnum):
    READY = "ready"
    NOT_CONFIGURED = "not_configured"
    DISTURBED = "disturbed"
    UNVERIFIED = "unverified"


class ProviderRouteCapability(StrEnum):
    TOOLS_AVAILABLE = "tools_available"
    TEXT_ONLY = "text_only"


class ProviderNeed(StrEnum):
    CLI_LOGIN = "cli_login"
    API_KEY = "api_key"


@dataclass(frozen=True)
class ConfiguredProvider:
    provider: str
    method: ProviderSetupMethod
    environment_key: str | None = None


@dataclass(frozen=True)
class CliLoginNeedsApiKeyProvider:
    provider: str
    method: ProviderSetupMethod
    missing_environment_key: str


@dataclass(frozen=True)
class ApiKeyNeedsCliLoginProvider:
    provider: str


@dataclass(frozen=True)
class UnconfiguredProvider:
    provider: str
    need: ProviderNeed
    missing_environment_key: str | None = None


@dataclass(frozen=True)
class DependencyUnavailableProvider:
    provider: str
    dependency: str


type ProviderConfiguration = (
    ConfiguredProvider
    | CliLoginNeedsApiKeyProvider
    | ApiKeyNeedsCliLoginProvider
    | DependencyUnavailableProvider
    | UnconfiguredProvider
)


@dataclass(frozen=True)
class ProviderSnapshot:
    cowriter: ProviderConfiguration
    judge: ProviderConfiguration
    probed_at: datetime
    routes: dict[ProviderRoute, "ProviderRouteSnapshot"]


@dataclass(frozen=True)
class ProviderRouteSnapshot:
    models: tuple[str, ...]
    catalogue_failure: SafeRouteReason | None
    catalog_source: str | None
    catalog_version: str | None
    readiness: ProviderRouteReadinessState
    capability: ProviderRouteCapability
    reason: SafeRouteReason | None
    probed_at: datetime
    setup_label: str


@dataclass(frozen=True)
class _ProviderApiCredential:
    secret: SecretStr | None
    environment_key: str


def get_provider_configuration(
    provider: str,
    surface: ProviderSurface,
) -> ProviderConfiguration:
    return _provider_configuration(provider, surface, get_settings())


def provider_snapshot(provider: str) -> ProviderSnapshot | None:
    """Return a provider's last background refresh without probing."""
    with _provider_snapshots_lock:
        return _provider_snapshots.get(provider)


def provider_snapshots() -> dict[str, ProviderSnapshot]:
    """Return one consistent view of the background provider refreshes."""
    with _provider_snapshots_lock:
        return dict(_provider_snapshots)


def refresh_provider_snapshot(provider: str) -> ProviderSnapshot:
    """Refresh one provider's reachability and model catalog."""
    settings = get_settings()
    routes = {
        route: _refresh_provider_route(provider, route, settings)
        for route in ProviderRoute
    }
    cowriter = get_provider_configuration(provider, ProviderSurface.CO_WRITER)
    judge = get_provider_configuration(provider, ProviderSurface.JUDGE)
    snapshot = ProviderSnapshot(
        cowriter=cowriter,
        judge=judge,
        probed_at=datetime.now(timezone.utc),
        routes=routes,
    )
    with _provider_snapshots_lock:
        _provider_snapshots[provider] = snapshot
    return snapshot


def _refresh_provider_route(
    provider: str,
    route: ProviderRoute,
    settings: Settings,
) -> ProviderRouteSnapshot:
    now = datetime.now(timezone.utc)
    capability = provider_route_capability()
    credential = _provider_api_credential(provider, settings)
    preflight = _provider_route_preflight(provider, route, credential, capability, now)
    if preflight is not None:
        return preflight
    try:
        models = tuple(list_provider_models(provider, route))
    except ProviderModelCatalogUnavailableError as exc:
        reason = exc.reason or normalize_route_failure(
            SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR,
        )
        return ProviderRouteSnapshot(
            (), reason, None, None, ProviderRouteReadinessState.DISTURBED,
            capability, reason, now,
            _CLI_LOGIN_SETUP_LABEL if route is ProviderRoute.CLI else _API_KEY_SETUP_LABEL,
        )
    except ProviderUnavailableError as exc:
        reason = exc.reason or normalize_route_failure(
            SafeRouteReasonCode.ROUTE_FAILED,
        )
        return ProviderRouteSnapshot(
            (), reason, None, None, ProviderRouteReadinessState.DISTURBED,
            capability, reason, now,
            _CLI_LOGIN_SETUP_LABEL if route is ProviderRoute.CLI else _API_KEY_SETUP_LABEL,
        )
    if provider == _CODEX_PROVIDER and route is ProviderRoute.CLI:
        source = _CODEX_CLI_KNOWN_MODELS_SOURCE
    elif route is ProviderRoute.API:
        source = "provider API"
    else:
        source = "provider CLI"
    return ProviderRouteSnapshot(
        models, None, source, None, ProviderRouteReadinessState.READY,
        capability, None, now,
        _CLI_LOGIN_SETUP_LABEL if route is ProviderRoute.CLI else _API_KEY_SETUP_LABEL,
    )


def _provider_route_preflight(
    provider: str,
    route: ProviderRoute,
    credential: _ProviderApiCredential,
    capability: ProviderRouteCapability,
    now: datetime,
) -> ProviderRouteSnapshot | None:
    if route is ProviderRoute.API:
        return _api_route_preflight(provider, credential, capability, now)
    return _cli_route_preflight(provider, capability, now)


def _api_route_preflight(
    provider: str,
    credential: _ProviderApiCredential,
    capability: ProviderRouteCapability,
    now: datetime,
) -> ProviderRouteSnapshot | None:
    if not _secret(credential.secret):
        return _route_preflight_snapshot(
            capability, now, ProviderRouteReadinessState.NOT_CONFIGURED,
            SafeRouteReasonCode.API_KEY_NOT_SET, _API_KEY_SETUP_LABEL,
        )
    if provider == _CLAUDE_PROVIDER and not _anthropic_sdk_available():
        return _route_preflight_snapshot(
            capability, now, ProviderRouteReadinessState.DISTURBED,
            SafeRouteReasonCode.API_HTTP_ERROR, _API_KEY_SETUP_LABEL,
        )
    return None


def _cli_route_preflight(
    provider: str,
    capability: ProviderRouteCapability,
    now: datetime,
) -> ProviderRouteSnapshot | None:
    try:
        if _cli_is_logged_in(provider):
            return None
    except AgentCliUnavailableError:
        return _route_preflight_snapshot(
            capability, now, ProviderRouteReadinessState.DISTURBED,
            SafeRouteReasonCode.CLI_BINARY_UNAVAILABLE, _CLI_LOGIN_SETUP_LABEL,
        )
    return _route_preflight_snapshot(
        capability, now, ProviderRouteReadinessState.NOT_CONFIGURED,
        SafeRouteReasonCode.CLI_LOGIN_NOT_CONFIGURED, _CLI_LOGIN_SETUP_LABEL,
    )


def _route_preflight_snapshot(
    capability: ProviderRouteCapability,
    now: datetime,
    readiness: ProviderRouteReadinessState,
    reason_code: SafeRouteReasonCode,
    setup_label: str,
) -> ProviderRouteSnapshot:
    return ProviderRouteSnapshot(
        (), None, None, None, readiness, capability,
        normalize_route_failure(reason_code), now, setup_label,
    )


def provider_route_capability() -> ProviderRouteCapability:
    """Return the fixed feature capability of a provider transport route."""
    return ProviderRouteCapability.TOOLS_AVAILABLE


def _cli_is_logged_in(provider: str) -> bool:
    if provider == _CLAUDE_PROVIDER:
        return cli_login_status().logged_in
    if provider == _GROK_PROVIDER:
        return grok_cli_status().login.logged_in
    if provider == _CODEX_PROVIDER:
        return codex_cli_login().logged_in
    raise ValueError(f"Unknown co-writer provider '{provider}'")


def clear_provider_snapshots() -> None:
    with _provider_snapshots_lock:
        _provider_snapshots.clear()


def list_provider_models(provider: str, route: ProviderRoute) -> list[str]:
    settings = get_settings()
    if provider not in COWRITER_PROVIDERS:
        raise ProviderUnavailableError(provider, f"Unknown co-writer provider '{provider}'")
    if route is ProviderRoute.CLI:
        return _models_for_setup_method(provider, _cli_setup_method_for(provider), settings)
    key = _secret(_provider_api_credential(provider, settings).secret)
    if not key:
        raise ProviderUnavailableError(
            provider, route.value, normalize_route_failure(SafeRouteReasonCode.API_KEY_NOT_SET),
        )
    return _models_for_setup_method(provider, ProviderSetupMethod.API_KEY, settings)


def _cli_setup_method_for(provider: str) -> ProviderSetupMethod:
    if provider == _CLAUDE_PROVIDER:
        return ProviderSetupMethod.CLAUDE_CLI
    if provider == _GROK_PROVIDER:
        return ProviderSetupMethod.GROK_CLI
    if provider == _CODEX_PROVIDER:
        return ProviderSetupMethod.CODEX_CLI
    raise ValueError(f"Unknown co-writer provider '{provider}'")


def models_with_active_model(models: list[str], active_model: str | None) -> list[str]:
    catalog = list(models)
    if active_model and active_model not in catalog:
        catalog.append(active_model)
    return catalog


def _models_for_setup_method(
    provider: str,
    method: ProviderSetupMethod,
    settings: Settings,
) -> list[str]:
    if method is ProviderSetupMethod.CLAUDE_CLI:
        return _list_claude_cli_models()
    if method is ProviderSetupMethod.GROK_CLI:
        return _list_grok_cli_models()
    if method is ProviderSetupMethod.CODEX_CLI:
        return list(_CODEX_CLI_KNOWN_MODELS)

    key = _secret(_provider_api_credential(provider, settings).secret)
    if provider == _GROK_PROVIDER:
        return _list_grok_models(key)
    if provider == _CODEX_PROVIDER:
        return _list_openai_models(key)
    if provider == _CLAUDE_PROVIDER:
        return _list_claude_models(key)
    raise ProviderUnavailableError(
        provider,
        f"Unknown co-writer provider '{provider}'",
    )


def _provider_configuration(
    provider: str,
    surface: ProviderSurface,
    settings: Settings,
) -> ProviderConfiguration:
    credential = _provider_api_credential(provider, settings)
    key_is_set = bool(_secret(credential.secret))
    cli_method = _cli_setup_method(provider)
    if key_is_set:
        if provider == _CLAUDE_PROVIDER and not _anthropic_sdk_available():
            return DependencyUnavailableProvider(
                provider,
                _ANTHROPIC_SDK_DISTRIBUTION,
            )
        return ConfiguredProvider(
            provider,
            ProviderSetupMethod.API_KEY,
            credential.environment_key,
        )
    if cli_method is not None and _cli_carries(cli_method, surface):
        return ConfiguredProvider(provider, cli_method)
    if cli_method is not None:
        return CliLoginNeedsApiKeyProvider(
            provider,
            cli_method,
            credential.environment_key,
        )
    if key_is_set:
        return ApiKeyNeedsCliLoginProvider(provider)
    need = ProviderNeed.API_KEY
    return UnconfiguredProvider(
        provider,
        need,
        credential.environment_key if need is ProviderNeed.API_KEY else None,
    )


def _cli_carries(method: ProviderSetupMethod, surface: ProviderSurface) -> bool:
    return method is ProviderSetupMethod.CLAUDE_CLI or (
        method in {ProviderSetupMethod.GROK_CLI, ProviderSetupMethod.CODEX_CLI}
        and surface is ProviderSurface.CO_WRITER
    )


def _cli_setup_method(provider: str) -> ProviderSetupMethod | None:
    try:
        if provider == _CLAUDE_PROVIDER and cli_login_status().logged_in:
            return ProviderSetupMethod.CLAUDE_CLI
        if provider == _GROK_PROVIDER and grok_cli_token_is_present():
            return ProviderSetupMethod.GROK_CLI
        if provider == _CODEX_PROVIDER and codex_cli_access_token_is_present():
            return ProviderSetupMethod.CODEX_CLI
    except AgentCliUnavailableError as exc:
        log.warning("%s CLI probe unavailable: %s", provider, type(exc).__name__)
    return None


def _anthropic_sdk_available() -> bool:
    try:
        return find_spec(_ANTHROPIC_SDK_DISTRIBUTION) is not None
    except ModuleNotFoundError:
        return False


def _provider_api_credential(
    provider: str, settings: Settings,
) -> _ProviderApiCredential:
    if provider == _CLAUDE_PROVIDER:
        return _ProviderApiCredential(
            settings.anthropic_api_key, ANTHROPIC_API_KEY_ENVIRONMENT,
        )
    if provider == _GROK_PROVIDER:
        return _ProviderApiCredential(
            settings.xai_api_key, XAI_API_KEY_ENVIRONMENT,
        )
    if provider == _CODEX_PROVIDER:
        return _ProviderApiCredential(
            settings.openai_api_key, OPENAI_API_KEY_ENVIRONMENT,
        )
    if provider not in COWRITER_PROVIDERS:
        raise ProviderUnavailableError(
            provider, f"Unknown co-writer provider '{provider}'",
        )
    raise ProviderUnavailableError(
        provider, f"No API credential is defined for co-writer provider '{provider}'",
    )


def _secret(value) -> str:
    if value is None:
        return ""
    return value.get_secret_value()


def _http_model_ids(url: str, headers: dict[str, str], provider: str) -> list[str]:
    try:
        response = httpx.get(
            url, headers=headers, timeout=COWRITER_MODELS_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise ProviderModelCatalogUnavailableError(
            provider,
            f"could not list {provider} models",
            normalize_route_failure(SafeRouteReasonCode.CATALOGUE_HTTP_ERROR),
        ) from exc
    if response.status_code >= 400:
        raise ProviderModelCatalogUnavailableError(
            provider,
            f"could not list {provider} models",
            normalize_route_failure(SafeRouteReasonCode.CATALOGUE_HTTP_ERROR),
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderModelCatalogUnavailableError(
            provider,
            f"could not list {provider} models",
            normalize_route_failure(SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR),
        ) from exc
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ProviderModelCatalogUnavailableError(
            provider,
            f"could not list {provider} models",
            normalize_route_failure(SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR),
        )
    ids: list[str] = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            ids.append(row["id"])
    return ids


def _list_grok_models(key: str) -> list[str]:
    ids = _http_model_ids(
        COWRITER_GROK_MODELS_URL,
        {"Authorization": f"Bearer {key}"},
        _GROK_PROVIDER,
    )
    chat = [
        model_id for model_id in ids
        if _is_provider_model_id(_GROK_PROVIDER, model_id)
    ]
    if not chat:
        raise ProviderModelCatalogUnavailableError(
            _GROK_PROVIDER,
            "no chat models returned by grok",
            normalize_route_failure(SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR),
        )
    return sorted(chat)


def _list_grok_cli_models() -> list[str]:
    try:
        model_names = grok_cli_status().model_names
    except AgentCliUnavailableError as exc:
        raise ProviderModelCatalogUnavailableError(
            _GROK_PROVIDER,
            "could not list grok CLI models",
            normalize_route_failure(SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR),
        ) from exc
    chat = [
        model_id for model_id in model_names
        if _is_provider_model_id(_GROK_PROVIDER, model_id)
    ]
    if not chat:
        raise ProviderModelCatalogUnavailableError(
            _GROK_PROVIDER,
            "no chat models returned by grok CLI",
            normalize_route_failure(SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR),
        )
    return sorted(chat)


def _list_openai_models(key: str) -> list[str]:
    ids = _http_model_ids(
        COWRITER_OPENAI_MODELS_URL,
        {"Authorization": f"Bearer {key}"},
        _CODEX_PROVIDER,
    )
    chat = [
        model_id for model_id in ids
        if _is_provider_model_id(_CODEX_PROVIDER, model_id)
    ]
    if not chat:
        raise ProviderModelCatalogUnavailableError(
            _CODEX_PROVIDER,
            "no chat models returned by codex",
            normalize_route_failure(SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR),
        )
    return sorted(chat)


def _list_claude_cli_models() -> list[str]:
    try:
        aliases = list_cli_model_aliases()
    except ClaudeCliUnavailableError as exc:
        raise ProviderModelCatalogUnavailableError(
            _CLAUDE_PROVIDER,
            CLAUDE_CLI_MODEL_CATALOG_ERROR,
            normalize_route_failure(SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR),
        ) from exc
    if not aliases:
        raise ProviderModelCatalogUnavailableError(
            _CLAUDE_PROVIDER,
            "no chat models returned by claude CLI",
            normalize_route_failure(SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR),
        )
    return sorted(aliases)


def _list_claude_models(key: str) -> list[str]:
    ids = _http_model_ids(
        COWRITER_ANTHROPIC_MODELS_URL,
        {
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_API_VERSION,
        },
        _CLAUDE_PROVIDER,
    )
    chat = [
        model_id for model_id in ids
        if _is_provider_model_id(_CLAUDE_PROVIDER, model_id)
    ]
    if not chat:
        raise ProviderModelCatalogUnavailableError(
            _CLAUDE_PROVIDER,
            "no chat models returned by claude",
            normalize_route_failure(SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR),
        )
    return sorted(chat)


def _contains_marker(model_id: str, markers: tuple[str, ...]) -> bool:
    lowered = model_id.lower()
    return any(marker in lowered for marker in markers)


def _is_provider_model_id(provider: str, model_id: str) -> bool:
    if provider == _CLAUDE_PROVIDER:
        return model_id.startswith(COWRITER_CLAUDE_MODEL_PREFIX)
    if provider == _GROK_PROVIDER:
        return (
            model_id.startswith(COWRITER_GROK_MODEL_PREFIX)
            and not _contains_marker(model_id, COWRITER_GROK_NON_CHAT_MARKERS)
        )
    if provider == _CODEX_PROVIDER:
        return (
            model_id.startswith(COWRITER_OPENAI_CHAT_PREFIXES)
            and not _contains_marker(model_id, COWRITER_OPENAI_NON_CHAT_MARKERS)
        )
    return False
