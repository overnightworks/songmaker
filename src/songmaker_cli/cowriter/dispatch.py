"""Route a co-writer turn through the explicitly selected provider transport."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy.orm import Session

from songmaker_cli.agent_cli import (
    AgentCliUnavailableError,
    codex_cli_access_token_is_present,
)
from songmaker_cli.claude.provider import (
    StreamEvent,
)
from songmaker_cli.claude.provider import (
    UnavailableError as ClaudeUnavailableError,
)
from songmaker_cli.constants import (
    COWRITER_GROK_CHAT_URL,
    COWRITER_OPENAI_CHAT_URL,
    COWRITER_PROVIDERS,
)
from songmaker_cli.cowriter.catalog import (
    ProviderRoute,
    ProviderSetupMethod,
)
from songmaker_cli.cowriter.claude_adapter import call_claude_once, stream_claude_turn
from songmaker_cli.cowriter.codex_cli_adapter import stream_codex_cli_turn
from songmaker_cli.cowriter.errors import (
    ProviderUnavailableError,
    SafeRouteReasonCode,
    normalize_route_failure,
)
from songmaker_cli.cowriter.grok_cli_adapter import stream_grok_cli_turn
from songmaker_cli.cowriter.openai_adapter import (
    call_openai_compatible_once,
    stream_openai_compatible_turn,
)
from songmaker_cli.middleware import AuthenticatedUser
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)


async def stream_cowriter_turn(
    *,
    provider: str,
    route: ProviderRoute,
    model: str,
    user_id: str,
    system: str,
    messages: list[dict[str, str]],
    session: Session,
    user: AuthenticatedUser,
) -> AsyncIterator[StreamEvent]:
    if provider not in COWRITER_PROVIDERS:
        raise _unavailable(provider, route, SafeRouteReasonCode.ROUTE_FAILED)
    if not model:
        raise _unavailable(provider, route, SafeRouteReasonCode.ROUTE_FAILED)
    if provider == "claude" and route is ProviderRoute.API:
        raise _unavailable(provider, route, SafeRouteReasonCode.CLAUDE_API_TOOL_LOOP_PENDING)
    try:
        stream = _stream_for_route(
            provider=provider,
            route=route,
            model=model,
            user_id=user_id,
            system=system,
            messages=messages,
            session=session,
            user=user,
        )
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()
    except ProviderUnavailableError as exc:
        if exc.reason is not None:
            raise
        raise _unavailable(provider, route, SafeRouteReasonCode.ROUTE_FAILED) from exc
    except Exception as exc:
        log.warning(
            "Co-writer adapter failed provider=%s route=%s class=%s",
            provider,
            route,
            type(exc).__name__,
        )
        raise _unavailable(provider, route, SafeRouteReasonCode.ROUTE_FAILED) from exc


def _stream_for_route(
    *,
    provider: str,
    route: ProviderRoute,
    model: str,
    user_id: str,
    system: str,
    messages: list[dict[str, str]],
    session: Session,
    user: AuthenticatedUser,
) -> AsyncIterator[StreamEvent]:
    if route is ProviderRoute.CLI:
        if provider == "claude":
            return stream_claude_turn(
                user_id=user_id, system=system, model=model, messages=messages,
            )
        if provider == "grok":
            return stream_grok_cli_turn(system=system, model=model, messages=messages)
        return stream_codex_cli_turn(system=system, model=model, messages=messages)
    api_key, api_url = _api_connection(provider)
    return stream_openai_compatible_turn(
        provider=provider,
        api_url=api_url,
        api_key=api_key,
        model=model,
        system=system,
        messages=messages,
        session=session,
        user=user,
    )


def call_provider_once(
    *, provider: str, model: str, prompt: str, timeout: int, system: str | None = None,
) -> str:
    """Call the Judge's API-only, tool-free provider adapter."""
    if provider not in COWRITER_PROVIDERS or not model:
        raise _unavailable(provider, ProviderRoute.API, SafeRouteReasonCode.ROUTE_FAILED)
    try:
        if provider == "claude":
            return call_claude_once(model=model, prompt=prompt, timeout=timeout, system=system)
        api_key, api_url = _api_connection(provider)
        return call_openai_compatible_once(
            provider=provider, api_url=api_url, api_key=api_key, model=model,
            prompt=prompt, timeout=timeout, system=system,
        )
    except ClaudeUnavailableError:
        raise
    except ProviderUnavailableError as exc:
        if exc.reason is not None:
            raise
        raise _unavailable(provider, ProviderRoute.API, SafeRouteReasonCode.ROUTE_FAILED) from exc
    except Exception as exc:
        log.warning("Judge adapter failed provider=%s class=%s", provider, type(exc).__name__)
        raise _unavailable(provider, ProviderRoute.API, SafeRouteReasonCode.ROUTE_FAILED) from exc


def _api_connection(provider: str) -> tuple[str, str]:
    settings = get_settings()
    if provider == "grok":
        return (
            _require_secret(provider, ProviderRoute.API, settings.xai_api_key),
            COWRITER_GROK_CHAT_URL,
        )
    if provider == "codex":
        return (
            _require_secret(provider, ProviderRoute.API, settings.openai_api_key),
            COWRITER_OPENAI_CHAT_URL,
        )
    raise _unavailable(
        provider,
        ProviderRoute.API,
        SafeRouteReasonCode.CLAUDE_API_TOOL_LOOP_PENDING,
    )


def _require_secret(provider: str, route: ProviderRoute, secret) -> str:
    value = secret.get_secret_value() if secret is not None else ""
    if not value:
        raise _unavailable(provider, route, SafeRouteReasonCode.API_KEY_NOT_SET)
    return value


def _codex_cli_access_token_is_present() -> bool:
    try:
        return codex_cli_access_token_is_present()
    except AgentCliUnavailableError as exc:
        raise _unavailable(
            "codex",
            ProviderRoute.CLI,
            SafeRouteReasonCode.CLI_BINARY_UNAVAILABLE,
        ) from exc


def cover_image_provider_method() -> ProviderSetupMethod | None:
    """Choose the one configured route for a generated cover image.

    Cover generation intentionally has no HTTP/API fallback.  The image
    adapter receives only this selected method and never reads credentials.
    """
    if _codex_cli_access_token_is_present():
        return ProviderSetupMethod.CODEX_CLI
    return None


def _unavailable(
    provider: str,
    route: ProviderRoute,
    code: SafeRouteReasonCode,
) -> ProviderUnavailableError:
    return ProviderUnavailableError(provider, route.value, normalize_route_failure(code))
