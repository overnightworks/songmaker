"""Songmaker's two provider surfaces and the last thing we know about them.

The provider layer answers per provider and per route. Songmaker projects
these snapshots onto the co-writer's and judge's saved routes. The judge's
actual call path remains owned by the scoring worker until #844's handoff.

Probing is expensive, so a background loop refreshes one snapshot per provider
and every reader — the settings API, the admin "Models" table — projects that
snapshot instead of probing inside a request.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from agent_providers.catalog import (
    ProviderRoute,
    ProviderRouteSnapshot,
    probe_provider_route,
)


@dataclass(frozen=True)
class ProviderSnapshot:
    probed_at: datetime
    routes: dict[ProviderRoute, ProviderRouteSnapshot]


_provider_snapshots_lock = threading.Lock()
_provider_snapshots: dict[str, ProviderSnapshot] = {}


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
        probed_at=datetime.now(timezone.utc),
        routes=routes,
    )
    with _provider_snapshots_lock:
        _provider_snapshots[provider] = snapshot
    return snapshot


def clear_provider_snapshots() -> None:
    with _provider_snapshots_lock:
        _provider_snapshots.clear()
