"""Live co-writer model catalogs from each provider API.

Model ids are never hardcoded. A failed catalog fetch is a named error,
not a fallback list.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from importlib.util import find_spec
from typing import Final

import httpx
from pydantic import SecretStr

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
_ANTHROPIC_API_KEY_ENVIRONMENT: Final = "ANTHROPIC_API_KEY"
_XAI_API_KEY_ENVIRONMENT: Final = "XAI_API_KEY"
_OPENAI_API_KEY_ENVIRONMENT: Final = "OPENAI_API_KEY"


class ProviderSetupMethod(StrEnum):
    API_KEY = "api_key"
    CLAUDE_CLI = "claude_cli"


@dataclass(frozen=True)
class ConfiguredProvider:
    provider: str
    method: ProviderSetupMethod


@dataclass(frozen=True)
class UnconfiguredProvider:
    provider: str
    missing_environment_key: str


@dataclass(frozen=True)
class DependencyUnavailableProvider:
    provider: str
    dependency: str


type ProviderConfiguration = (
    ConfiguredProvider | DependencyUnavailableProvider | UnconfiguredProvider
)


@dataclass(frozen=True)
class _ProviderApiCredential:
    secret: SecretStr | None
    environment_key: str


def get_provider_configuration(provider: str) -> ProviderConfiguration:
    return _provider_configuration(provider, get_settings())


def list_provider_models(provider: str) -> list[str]:
    settings = get_settings()
    configuration = _provider_configuration(provider, settings)
    if isinstance(configuration, DependencyUnavailableProvider):
        raise ProviderUnavailableError(
            provider,
            f"{provider} is unavailable: required dependency "
            f"'{configuration.dependency}' is not installed",
        )
    if isinstance(configuration, UnconfiguredProvider):
        raise ProviderUnavailableError(
            provider,
            f"{provider} is not configured: missing "
            f"{configuration.missing_environment_key}",
        )
    if configuration.method is ProviderSetupMethod.CLAUDE_CLI:
        return _list_claude_cli_models()

    key = _secret(_provider_api_credential(provider, settings).secret)
    if provider == _GROK_PROVIDER:
        return _list_grok_models(key)
    if provider == _CODEX_PROVIDER:
        return _list_openai_models(key)
    if provider == _CLAUDE_PROVIDER:
        return _list_claude_models(key)
    raise ProviderUnavailableError(
        provider, f"Unknown co-writer provider '{provider}'",
    )


def _provider_configuration(
    provider: str, settings: Settings,
) -> ProviderConfiguration:
    credential = _provider_api_credential(provider, settings)
    if _secret(credential.secret):
        if provider == _CLAUDE_PROVIDER and not _anthropic_sdk_available():
            return DependencyUnavailableProvider(
                provider, _ANTHROPIC_SDK_DISTRIBUTION,
            )
        return ConfiguredProvider(provider, ProviderSetupMethod.API_KEY)
    if provider == _CLAUDE_PROVIDER and cli_login_status().logged_in:
        return ConfiguredProvider(provider, ProviderSetupMethod.CLAUDE_CLI)
    return UnconfiguredProvider(provider, credential.environment_key)


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
            settings.anthropic_api_key, _ANTHROPIC_API_KEY_ENVIRONMENT,
        )
    if provider == _GROK_PROVIDER:
        return _ProviderApiCredential(
            settings.xai_api_key, _XAI_API_KEY_ENVIRONMENT,
        )
    if provider == _CODEX_PROVIDER:
        return _ProviderApiCredential(
            settings.openai_api_key, _OPENAI_API_KEY_ENVIRONMENT,
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
        if model_id.startswith(COWRITER_GROK_MODEL_PREFIX)
        and not _contains_marker(model_id, COWRITER_GROK_NON_CHAT_MARKERS)
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
        if model_id.startswith(COWRITER_OPENAI_CHAT_PREFIXES)
        and not _contains_marker(model_id, COWRITER_OPENAI_NON_CHAT_MARKERS)
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
        if model_id.startswith(COWRITER_CLAUDE_MODEL_PREFIX)
    ]
    if not chat:
        raise ProviderModelCatalogUnavailableError(
            _CLAUDE_PROVIDER, "no chat models returned by claude",
        )
    return sorted(chat)


def _contains_marker(model_id: str, markers: tuple[str, ...]) -> bool:
    lowered = model_id.lower()
    return any(marker in lowered for marker in markers)
