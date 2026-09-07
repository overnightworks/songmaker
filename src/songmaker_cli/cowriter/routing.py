"""Which provider runs a musician's turn, and with whose permissions.

The provider layer executes a named route. Songmaker decides which route that
is and who the turn acts for: it binds the request session and the
authenticated musician to the tool executor, hands over the tool catalog, and
resolves the saved cover selection — product decisions the library must not
make on a host's behalf.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy.orm import Session
from webauth.dependencies import AuthenticatedUser

from agent_providers.catalog import ProviderRoute
from agent_providers.dispatch import cover_image_capability
from agent_providers.dispatch import stream_cowriter_turn as stream_provider_turn
from agent_providers.errors import (
    ProviderUnavailableError,
    SafeRouteReasonCode,
    normalize_route_failure,
)
from agent_providers.events import StreamEvent
from agent_providers.tool_loop import ToolExecutor
from agent_providers.tools import ToolCatalog
from songmaker_cli.cover_job_errors import CoverImageToolUnavailableError
from songmaker_cli.db.queries.settings import get_cover_settings


@dataclass(frozen=True)
class CoverImageDispatch:
    """The saved cover route, verified to own an image tool, and its model."""

    provider: str
    route: ProviderRoute
    model: str


def stream_cowriter_turn(
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
    """Run one co-writer turn with this musician's tools and permissions."""
    return stream_provider_turn(
        provider=provider,
        route=route,
        model=model,
        user_id=user_id,
        system=system,
        messages=messages,
        executor=_cowriter_executor(session, user),
        catalog=_tool_catalog(),
        correlation_id=correlation_id,
    )


def _tool_catalog() -> ToolCatalog:
    """Load songmaker's tool catalog only where a tool-using turn needs it.

    Its module reaches the MCP tool implementations, and the scoring worker
    installs no ``mcp`` extra, so importing it at module scope would keep
    that container from importing this module at all.
    """
    from songmaker_cli.cowriter.tools import COWRITER_TOOL_CATALOG

    return COWRITER_TOOL_CATALOG


def _cowriter_executor(session: Session, user: AuthenticatedUser) -> ToolExecutor:
    """Bind the requesting musician's session to songmaker's tool executor."""
    from songmaker_cli.cowriter.tools import execute_cowriter_tool

    return lambda name, arguments: execute_cowriter_tool(session, user, name, arguments)


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
