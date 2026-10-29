"""Provider runtime configuration a test replaces for itself."""

from __future__ import annotations


def override_provider_runtime(**deployment_facts) -> None:
    """Replace named provider deployment facts for the current test only.

    Test doubles for a mounted binary, credential mirror, or resource
    directory belong here rather than in a patched module constant: the
    provider layer reads them from the injected configuration, which the
    autouse fixture in ``conftest.py`` rebuilds for every test.

    Deliberately replaces the installation rather than adding to it, because
    ``configure()`` refuses a differing second value. A test that overrides
    before building its app therefore fails loudly when ``create_app``
    installs songmaker's own facts over it, instead of silently losing them.
    """
    from agent_providers.config import (
        ProviderRuntimeConfig,
        configure,
        current_config,
        reset_config,
    )

    replacement = ProviderRuntimeConfig(
        **{**current_config().model_dump(), **deployment_facts},
    )
    reset_config()
    configure(replacement)


def use_codex_process_pool(monkeypatch, process_pool) -> None:
    """Give every Codex module that admits a process the same test pool.

    Admission is asked for in three places — the tool transport, the image
    route, and the shared runner that binds and reaps a reservation — so a
    test that sizes the pool has to reach all three or it silently measures
    the process-wide one.
    """
    from agent_providers.codex import image, protocol, transport

    for module in (image, protocol, transport):
        monkeypatch.setattr(module, "get_codex_process_pool", lambda: process_pool)


def refresh_provider_snapshots() -> None:
    """Refresh every provider after a test changes its catalog dependencies."""
    from agent_providers.constants import COWRITER_PROVIDERS

    from songmaker_cli.provider_status import refresh_provider_snapshot

    for provider in COWRITER_PROVIDERS:
        refresh_provider_snapshot(provider)
