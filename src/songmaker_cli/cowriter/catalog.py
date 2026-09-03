"""Live co-writer model catalogs from each provider API.

Model ids are never hardcoded. A failed catalog fetch is a named error,
not a fallback list.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from importlib.util import find_spec
from typing import Final

import httpx
from pydantic import SecretStr

from songmaker_cli.agent_cli import (
    AgentCliUnavailableError,
    codex_cli_login,
    grok_cli_status,
)
from songmaker_cli.claude.provider import UnavailableError as ClaudeCliUnavailableError
from songmaker_cli.claude.provider import cli_login_status, list_cli_model_aliases
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
)
from songmaker_cli.settings import Settings, get_settings

_CLAUDE_PROVIDER: Final = "claude"
_GROK_PROVIDER: Final = "grok"
_CODEX_PROVIDER: Final = "codex"
_ANTHROPIC_SDK_DISTRIBUTION: Final = "anthropic"
ANTHROPIC_API_KEY_ENVIRONMENT: Final = "ANTHROPIC_API_KEY"
XAI_API_KEY_ENVIRONMENT: Final = "XAI_API_KEY"
OPENAI_API_KEY_ENVIRONMENT: Final = "OPENAI_API_KEY"

log = logging.getLogger(__name__)


class ProviderSetupMethod(StrEnum):
    API_KEY = "api_key"
    CLAUDE_CLI = "claude_cli"
    GROK_CLI = "grok_cli"
    CODEX_CLI = "codex_cli"


class ProviderSurface(StrEnum):
    CO_WRITER = "cowriter"
    JUDGE = "judge"


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
class _ProviderApiCredential:
    secret: SecretStr | None
    environment_key: str


def get_provider_configuration(
    provider: str,
    surface: ProviderSurface,
) -> ProviderConfiguration:
    return _provider_configuration(provider, surface, get_settings())


def list_provider_models(provider: str) -> list[str]:
    settings = get_settings()
    # The catalog is for models that can serve a turn; JUDGE is the weaker surface.
    configuration = _provider_configuration(provider, ProviderSurface.JUDGE, settings)
    match configuration:
        case ConfiguredProvider():
            return _models_for_setup_method(provider, configuration.method, settings)
        case DependencyUnavailableProvider():
            raise ProviderUnavailableError(
                provider,
                f"{provider} is unavailable: required dependency "
                f"'{configuration.dependency}' is not installed",
            )
        case CliLoginNeedsApiKeyProvider(missing_environment_key=environment_key):
            raise ProviderUnavailableError(
                provider,
                f"{provider} is not configured: missing {environment_key}",
            )
        case ApiKeyNeedsCliLoginProvider():
            raise ProviderUnavailableError(
                provider,
                f"{provider} cannot list models until its CLI login is available",
            )
        case UnconfiguredProvider(missing_environment_key=environment_key) if environment_key:
            raise ProviderUnavailableError(
                provider,
                f"{provider} is not configured: missing {environment_key}",
            )
        case UnconfiguredProvider():
            raise ProviderUnavailableError(
                provider,
                f"{provider} cannot list models until {configuration.need.value} is configured",
            )
    raise AssertionError(f"unhandled provider configuration state: {configuration!r}")


def models_with_active_model(
    provider: str,
    models: list[str],
    active_model: str | None,
) -> list[str]:
    catalog = list(models)
    if active_model and _is_provider_model_id(provider, active_model):
        if active_model not in catalog:
            catalog.append(active_model)
    return catalog


def _models_for_setup_method(
    provider: str,
    method: ProviderSetupMethod,
    settings: Settings,
) -> list[str]:
    if method is ProviderSetupMethod.CLAUDE_CLI:
        return _list_claude_cli_models()
    if method is ProviderSetupMethod.CODEX_CLI:
        raise ProviderModelCatalogUnavailableError(
            provider,
            "the codex CLI has no non-interactive model catalog — "
            f"set {OPENAI_API_KEY_ENVIRONMENT} to list codex models",
        )

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
    if key_is_set and _api_key_carries(provider, surface):
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
    cli_method = _cli_setup_method(provider)
    if cli_method is not None and _cli_carries(cli_method):
        return ConfiguredProvider(provider, cli_method)
    if cli_method is not None:
        return CliLoginNeedsApiKeyProvider(
            provider,
            cli_method,
            credential.environment_key,
        )
    if key_is_set:
        return ApiKeyNeedsCliLoginProvider(provider)
    need = _needed_setup(provider, surface)
    return UnconfiguredProvider(
        provider,
        need,
        credential.environment_key if need is ProviderNeed.API_KEY else None,
    )


def _api_key_carries(provider: str, surface: ProviderSurface) -> bool:
    return not (provider == _CLAUDE_PROVIDER and surface is ProviderSurface.CO_WRITER)


def _cli_carries(method: ProviderSetupMethod) -> bool:
    return method is ProviderSetupMethod.CLAUDE_CLI


def _needed_setup(provider: str, surface: ProviderSurface) -> ProviderNeed:
    if provider == _CLAUDE_PROVIDER and surface is ProviderSurface.CO_WRITER:
        return ProviderNeed.CLI_LOGIN
    return ProviderNeed.API_KEY


def _cli_setup_method(provider: str) -> ProviderSetupMethod | None:
    try:
        if provider == _CLAUDE_PROVIDER and cli_login_status().logged_in:
            return ProviderSetupMethod.CLAUDE_CLI
        if provider == _GROK_PROVIDER and grok_cli_status().login.logged_in:
            return ProviderSetupMethod.GROK_CLI
        if provider == _CODEX_PROVIDER and codex_cli_login().logged_in:
            return ProviderSetupMethod.CODEX_CLI
    except AgentCliUnavailableError as exc:
        log.warning("%s CLI probe unavailable: %s: %s", provider, type(exc).__name__, exc)
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
            provider, f"could not list {provider} models",
        ) from exc
    if response.status_code >= 400:
        raise ProviderModelCatalogUnavailableError(
            provider, f"could not list {provider} models",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderModelCatalogUnavailableError(
            provider, f"could not list {provider} models",
        ) from exc
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ProviderModelCatalogUnavailableError(
            provider, f"could not list {provider} models",
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
            _GROK_PROVIDER, "no chat models returned by grok",
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
            _CODEX_PROVIDER, "no chat models returned by codex",
        )
    return sorted(chat)


def _list_claude_cli_models() -> list[str]:
    try:
        aliases = list_cli_model_aliases()
    except ClaudeCliUnavailableError as exc:
        raise ProviderModelCatalogUnavailableError(
            _CLAUDE_PROVIDER, f"could not list claude CLI models: {exc}",
        ) from exc
    if not aliases:
        raise ProviderModelCatalogUnavailableError(
            _CLAUDE_PROVIDER, "no chat models returned by claude CLI",
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
            _CLAUDE_PROVIDER, "no chat models returned by claude",
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
