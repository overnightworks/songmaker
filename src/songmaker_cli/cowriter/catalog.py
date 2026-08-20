"""Live co-writer model catalogs from each provider API.

Model ids are never hardcoded. A failed catalog fetch is a named error,
not a fallback list.
"""

from __future__ import annotations

import httpx

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
from songmaker_cli.cowriter.errors import ProviderUnavailableError
from songmaker_cli.settings import get_settings


def list_provider_models(provider: str) -> list[str]:
    if provider not in COWRITER_PROVIDERS:
        raise ProviderUnavailableError(
            provider, f"Unknown co-writer provider '{provider}'",
        )
    if provider == "grok":
        return _list_grok_models()
    if provider == "codex":
        return _list_openai_models()
    return _list_claude_models()


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
        raise ProviderUnavailableError(
            provider, f"could not list {provider} models",
        ) from exc
    if response.status_code >= 400:
        raise ProviderUnavailableError(
            provider, f"could not list {provider} models",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderUnavailableError(
            provider, f"could not list {provider} models",
        ) from exc
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ProviderUnavailableError(
            provider, f"could not list {provider} models",
        )
    ids: list[str] = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            ids.append(row["id"])
    return ids


def _list_grok_models() -> list[str]:
    key = _secret(get_settings().xai_api_key)
    if not key:
        raise ProviderUnavailableError("grok", "grok is not configured")
    ids = _http_model_ids(
        COWRITER_GROK_MODELS_URL,
        {"Authorization": f"Bearer {key}"},
        "grok",
    )
    chat = [
        model_id for model_id in ids
        if model_id.startswith(COWRITER_GROK_MODEL_PREFIX)
        and not _contains_marker(model_id, COWRITER_GROK_NON_CHAT_MARKERS)
    ]
    if not chat:
        raise ProviderUnavailableError("grok", "no chat models returned by grok")
    return sorted(chat)


def _list_openai_models() -> list[str]:
    key = _secret(get_settings().openai_api_key)
    if not key:
        raise ProviderUnavailableError("codex", "codex is not configured")
    ids = _http_model_ids(
        COWRITER_OPENAI_MODELS_URL,
        {"Authorization": f"Bearer {key}"},
        "codex",
    )
    chat = [
        model_id for model_id in ids
        if model_id.startswith(COWRITER_OPENAI_CHAT_PREFIXES)
        and not _contains_marker(model_id, COWRITER_OPENAI_NON_CHAT_MARKERS)
    ]
    if not chat:
        raise ProviderUnavailableError("codex", "no chat models returned by codex")
    return sorted(chat)


def _list_claude_models() -> list[str]:
    key = _secret(get_settings().anthropic_api_key)
    if not key:
        raise ProviderUnavailableError("claude", "claude is not configured")
    ids = _http_model_ids(
        COWRITER_ANTHROPIC_MODELS_URL,
        {
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_API_VERSION,
        },
        "claude",
    )
    chat = [
        model_id for model_id in ids
        if model_id.startswith(COWRITER_CLAUDE_MODEL_PREFIX)
    ]
    if not chat:
        raise ProviderUnavailableError("claude", "no chat models returned by claude")
    return sorted(chat)


def _contains_marker(model_id: str, markers: tuple[str, ...]) -> bool:
    lowered = model_id.lower()
    return any(marker in lowered for marker in markers)
