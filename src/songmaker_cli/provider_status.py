"""Songmaker's two provider surfaces and the last thing we know about them.

The provider layer answers per provider and per route. Songmaker asks that
question for two surfaces: the co-writer, which runs a tool-using session and
can therefore use every mounted CLI, and the lyrical-coherence judge, which
needs one tool-free completion and reaches only Claude's CLI that way.

Probing is expensive, so a background loop refreshes one snapshot per provider
and every reader — the settings API, the admin "Models" table — projects that
snapshot instead of probing inside a request.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Final

from agent_providers.catalog import (
    ProviderConfiguration,
    ProviderRoute,
    ProviderRouteSnapshot,
    ProviderSetupMethod,
    probe_provider_route,
    provider_configuration,
)


class ProviderSurface(StrEnum):
    CO_WRITER = "cowriter"
    JUDGE = "judge"


_SURFACE_CLI_METHODS: Final[dict[ProviderSurface, frozenset[ProviderSetupMethod]]] = {
    ProviderSurface.CO_WRITER: frozenset({
        ProviderSetupMethod.CLAUDE_CLI,
        ProviderSetupMethod.GROK_CLI,
        ProviderSetupMethod.CODEX_CLI,
    }),
    ProviderSurface.JUDGE: frozenset({ProviderSetupMethod.CLAUDE_CLI}),
}


@dataclass(frozen=True)
class ProviderSnapshot:
    cowriter: ProviderConfiguration
    judge: ProviderConfiguration
    probed_at: datetime
    routes: dict[ProviderRoute, ProviderRouteSnapshot]


_provider_snapshots_lock = threading.Lock()
_provider_snapshots: dict[str, ProviderSnapshot] = {}


def get_provider_configuration(
    provider: str,
    surface: ProviderSurface,
) -> ProviderConfiguration:
    """Ask the provider layer how this provider is set up for that surface."""
    return provider_configuration(provider, _SURFACE_CLI_METHODS[surface])


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
    routes = {
        route: probe_provider_route(provider, route)
        for route in ProviderRoute
    }
    snapshot = ProviderSnapshot(
        cowriter=get_provider_configuration(provider, ProviderSurface.CO_WRITER),
        judge=get_provider_configuration(provider, ProviderSurface.JUDGE),
        probed_at=datetime.now(timezone.utc),
        routes=routes,
    )
    with _provider_snapshots_lock:
        _provider_snapshots[provider] = snapshot
    return snapshot


def clear_provider_snapshots() -> None:
    with _provider_snapshots_lock:
        _provider_snapshots.clear()
