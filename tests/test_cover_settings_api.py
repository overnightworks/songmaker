"""The cover settings endpoint names the providers a save accepts."""

from __future__ import annotations

from agent_providers.constants import COWRITER_PROVIDERS


def test_cover_allowed_providers_are_exactly_the_providers_a_save_accepts(admin_client):
    allowed = admin_client.get("/api/settings/cover").json()["allowed_providers"]

    assert allowed == sorted(COWRITER_PROVIDERS)
    for provider in allowed:
        response = admin_client.put(
            "/api/settings/cover",
            json={"provider": provider, "route": "cli", "model": ""},
        )
        assert response.status_code == 200
        assert response.json()["allowed_providers"] == allowed
