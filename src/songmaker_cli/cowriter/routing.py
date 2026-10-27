"""Which provider route paints a cover: the saved cover selection, resolved once.

The provider layer executes a named route. Songmaker decides which route the
saved cover selection names, a product decision the library must not make on a
host's behalf.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_providers.catalog import ProviderRoute
from agent_providers.dispatch import cover_image_capability
from agent_providers.errors import (
    ProviderUnavailableError,
    SafeRouteReasonCode,
    normalize_route_failure,
)
from sqlalchemy.orm import Session

from songmaker_cli.cover_job_errors import CoverImageToolUnavailableError
from songmaker_cli.db.queries.settings import get_cover_settings


@dataclass(frozen=True)
class CoverImageDispatch:
    """The saved cover route, verified to own an image tool, and its model."""

    provider: str
    route: ProviderRoute
    model: str


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
