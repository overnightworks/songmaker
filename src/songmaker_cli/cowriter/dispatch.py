"""Route a co-writer turn through the explicitly selected provider transport."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Final

from sqlalchemy.orm import Session

from agent_providers.claude.adapter import (
    call_claude_once,
    stream_claude_api_turn,
    stream_claude_turn,
)
from agent_providers.claude.provider import (
    UnavailableError as ClaudeUnavailableError,
)
from agent_providers.codex.image import codex_cover_image_capability_is_available
from agent_providers.codex.transport import CodexCliToolTransport
from agent_providers.config import current_config
from agent_providers.constants import (
    COWRITER_GROK_CHAT_URL,
    COWRITER_OPENAI_CHAT_URL,
    COWRITER_PROVIDERS,
)
from agent_providers.errors import (
    ProviderUnavailableError,
    SafeRouteReason,
    SafeRouteReasonCode,
    normalize_route_failure,
)
from agent_providers.events import StreamEvent
from agent_providers.grok.transport import GrokCliToolTransport
from agent_providers.openai_adapter import (
    call_openai_compatible_once,
    stream_openai_compatible_turn,
)
from agent_providers.process import (
    AgentCliUnavailableError,
    codex_cli_access_token_is_present,
)
from agent_providers.tool_loop import (
    ToolExecutor,
    ToolLoopLimitError,
    ToolLoopProtocolError,
    ToolTransport,
    stream_tool_loop,
)
from agent_providers.tools import (
    ToolCatalog,
    anthropic_tool_schemas,
    openai_tool_schemas,
)
from songmaker_cli.cover_job_errors import CoverImageToolUnavailableError
from songmaker_cli.cowriter.catalog import ProviderRoute
from songmaker_cli.db.queries.settings import get_cover_settings
from webauth.dependencies import AuthenticatedUser

log = logging.getLogger(__name__)

# Cover images come from Codex's CLI image turn; no other provider or route
# ships an image tool today (#822).
_IMAGE_TOOL_PROVIDER: Final[str] = "codex"
_IMAGE_TOOL_ROUTE: Final[ProviderRoute] = ProviderRoute.CLI


@dataclass(frozen=True)
class _ApiConnection:
    api_key: str
    api_url: str | None = None


@dataclass(frozen=True)
class CoverImageDispatch:
    """The saved cover route, verified to own an image tool, and its model."""

    provider: str
    route: ProviderRoute
    model: str


@dataclass(frozen=True)
class CoverImageCapability:
    """One route's image answer: does it own the tool, and what blocks it today."""

    carries_image_tool: bool
    failure: SafeRouteReason | None


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
    correlation_id: str | None = None,
) -> AsyncIterator[StreamEvent]:
    if provider not in COWRITER_PROVIDERS:
        raise _unavailable(provider, route, SafeRouteReasonCode.ROUTE_FAILED)
    if not model:
        raise _unavailable(provider, route, SafeRouteReasonCode.ROUTE_FAILED)
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
            correlation_id=correlation_id,
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
    correlation_id: str | None,
) -> AsyncIterator[StreamEvent]:
    if route is ProviderRoute.CLI:
        if provider == "claude":
            return stream_claude_turn(
                user_id=user_id,
                system=system,
                model=model,
                messages=messages,
                correlation_id=correlation_id,
            )
        if provider == "grok":
            return _stream_grok_cli_tool_turn(
                model=model,
                system=system,
                messages=messages,
                session=session,
                user=user,
                correlation_id=correlation_id,
            )
        if provider == "codex":
            return _stream_codex_cli_tool_turn(
                model=model,
                system=system,
                messages=messages,
                session=session,
                user=user,
                correlation_id=correlation_id,
            )
        raise _unavailable(provider, route, SafeRouteReasonCode.ROUTE_FAILED)
    connection = _api_connection(provider)
    catalog = _tool_catalog()
    executor = _cowriter_executor(session, user)
    if provider == "claude":
        return stream_claude_api_turn(
            api_key=connection.api_key,
            system=system,
            model=model,
            messages=messages,
            executor=executor,
            tool_schemas=anthropic_tool_schemas(catalog),
            correlation_id=correlation_id,
        )
    return stream_openai_compatible_turn(
        provider=provider,
        api_url=_require_api_url(provider, connection),
        api_key=connection.api_key,
        model=model,
        system=system,
        messages=messages,
        executor=executor,
        tool_schemas=openai_tool_schemas(catalog),
        correlation_id=correlation_id,
    )


async def _stream_grok_cli_tool_turn(
    *,
    model: str,
    system: str,
    messages: list[dict[str, str]],
    session: Session,
    user: AuthenticatedUser,
    correlation_id: str | None,
) -> AsyncIterator[StreamEvent]:
    """Run Grok's text protocol through the shared co-writer tool loop."""
    async for event in _stream_cli_tool_turn(
        provider="grok",
        system=system,
        messages=messages,
        session=session,
        user=user,
        transport=GrokCliToolTransport(model=model, catalog=_tool_catalog()),
        correlation_id=correlation_id,
    ):
        yield event


async def _stream_codex_cli_tool_turn(
    *,
    model: str,
    system: str,
    messages: list[dict[str, str]],
    session: Session,
    user: AuthenticatedUser,
    correlation_id: str | None,
) -> AsyncIterator[StreamEvent]:
    """Run Codex's text protocol through the shared co-writer tool loop."""
    async for event in _stream_cli_tool_turn(
        provider="codex",
        system=system,
        messages=messages,
        session=session,
        user=user,
        transport=CodexCliToolTransport(model=model, catalog=_tool_catalog()),
        correlation_id=correlation_id,
    ):
        yield event


def _tool_catalog() -> ToolCatalog:
    """Load songmaker's tool catalog only where a tool-using turn needs it.

    Its module reaches the MCP tool implementations, and the scoring worker
    installs no ``mcp`` extra, so importing it at module scope would keep
    that container from importing this router at all.
    """
    from songmaker_cli.cowriter.tools import COWRITER_TOOL_CATALOG

    return COWRITER_TOOL_CATALOG


def _cowriter_executor(session: Session, user: AuthenticatedUser) -> ToolExecutor:
    """Bind the requesting musician's session to songmaker's tool executor."""
    from songmaker_cli.cowriter.tools import execute_cowriter_tool

    return lambda name, arguments: execute_cowriter_tool(session, user, name, arguments)


async def _stream_cli_tool_turn(
    *,
    provider: str,
    system: str,
    messages: list[dict[str, str]],
    session: Session,
    user: AuthenticatedUser,
    transport: ToolTransport,
    correlation_id: str | None,
) -> AsyncIterator[StreamEvent]:
    """Run one CLI text-protocol transport through the authorized tool loop."""
    try:
        async for event in stream_tool_loop(
            provider=provider,
            route=ProviderRoute.CLI.value,
            system=system,
            messages=messages,
            transport=transport,
            executor=_cowriter_executor(session, user),
            tool_failure_message=normalize_route_failure(
                SafeRouteReasonCode.TOOL_EXECUTION_FAILED,
            ).message,
            correlation_id=correlation_id,
        ):
            yield event
    except ToolLoopLimitError as exc:
        raise _unavailable(
            provider, ProviderRoute.CLI, SafeRouteReasonCode.TOOL_LIMIT_EXCEEDED,
        ) from exc
    except ToolLoopProtocolError as exc:
        raise _unavailable(
            provider, ProviderRoute.CLI, SafeRouteReasonCode.TOOL_PROTOCOL_ERROR,
        ) from exc


def call_provider_once(
    *, provider: str, model: str, prompt: str, timeout: int, system: str | None = None,
) -> str:
    """Call the Judge's API-only, tool-free provider adapter."""
    if provider not in COWRITER_PROVIDERS or not model:
        raise _unavailable(provider, ProviderRoute.API, SafeRouteReasonCode.ROUTE_FAILED)
    try:
        if provider == "claude":
            return call_claude_once(model=model, prompt=prompt, timeout=timeout, system=system)
        connection = _api_connection(provider)
        return call_openai_compatible_once(
            provider=provider,
            api_url=_require_api_url(provider, connection),
            api_key=connection.api_key,
            model=model,
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


def _api_connection(provider: str) -> _ApiConnection:
    config = current_config()
    if provider == "claude":
        api_key = _require_secret(provider, ProviderRoute.API, config.anthropic_api_key)
        return _ApiConnection(api_key)
    if provider == "grok":
        return _ApiConnection(
            _require_secret(provider, ProviderRoute.API, config.xai_api_key),
            COWRITER_GROK_CHAT_URL,
        )
    if provider == "codex":
        return _ApiConnection(
            _require_secret(provider, ProviderRoute.API, config.openai_api_key),
            COWRITER_OPENAI_CHAT_URL,
        )
    raise _unavailable(provider, ProviderRoute.API, SafeRouteReasonCode.ROUTE_FAILED)


def _require_api_url(provider: str, connection: _ApiConnection) -> str:
    if connection.api_url is None:
        raise _unavailable(provider, ProviderRoute.API, SafeRouteReasonCode.ROUTE_FAILED)
    return connection.api_url


def _require_secret(provider: str, route: ProviderRoute, secret) -> str:
    value = secret.get_secret_value() if secret is not None else ""
    if not value:
        raise _unavailable(provider, route, SafeRouteReasonCode.API_KEY_NOT_SET)
    return value


def cover_image_capability(provider: str, route: ProviderRoute) -> CoverImageCapability:
    """Answer whether one provider route can create cover images, or name why not.

    Every caller that needs the answer — the cover job, the provider status,
    and the admin surface — asks here instead of deciding for itself.
    """
    if provider != _IMAGE_TOOL_PROVIDER or route is not _IMAGE_TOOL_ROUTE:
        return CoverImageCapability(
            carries_image_tool=False,
            failure=normalize_route_failure(SafeRouteReasonCode.NO_IMAGE_TOOL),
        )
    return CoverImageCapability(
        carries_image_tool=True, failure=_codex_cli_image_route_failure(),
    )


def _codex_cli_image_route_failure() -> SafeRouteReason | None:
    """Name what keeps the mounted Codex CLI from running an image turn."""
    if not codex_cover_image_capability_is_available():
        return normalize_route_failure(SafeRouteReasonCode.CLI_BINARY_UNAVAILABLE)
    try:
        signed_in = codex_cli_access_token_is_present()
    except AgentCliUnavailableError:
        return normalize_route_failure(SafeRouteReasonCode.CLI_BINARY_UNAVAILABLE)
    if not signed_in:
        return normalize_route_failure(SafeRouteReasonCode.CLI_LOGIN_NOT_CONFIGURED)
    return None


def cover_image_provider_method(session: Session) -> CoverImageDispatch:
    """Resolve the saved cover selection through the one image-capability owner."""
    selection = get_cover_settings(session)
    try:
        route = ProviderRoute(selection.route)
    except ValueError as exc:
        raise ProviderUnavailableError(
            selection.provider,
            selection.route,
            normalize_route_failure(SafeRouteReasonCode.ROUTE_FAILED),
        ) from exc
    capability = cover_image_capability(selection.provider, route)
    if not capability.carries_image_tool:
        raise CoverImageToolUnavailableError(selection.provider)
    if capability.failure is not None:
        raise ProviderUnavailableError(selection.provider, route.value, capability.failure)
    return CoverImageDispatch(provider=selection.provider, route=route, model=selection.model)


def _unavailable(
    provider: str,
    route: ProviderRoute,
    code: SafeRouteReasonCode,
) -> ProviderUnavailableError:
    return ProviderUnavailableError(provider, route.value, normalize_route_failure(code))
